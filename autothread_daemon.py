#!/usr/bin/env python3
"""
Auto-threading daemon for Telegram forums.

Monitors the General topic in configured forums and auto-threads
when new conversations are detected (user message + bot response).

Run as: python autothread_daemon.py --daemon
Or one-shot: python autothread_daemon.py --once
"""

import asyncio
import json
import time
import os
import argparse
import requests
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import traceback

# Config
CONFIG_DIR = Path(__file__).parent
STATE_PATH = CONFIG_DIR / "forum_state.json"
DAEMON_STATE_PATH = CONFIG_DIR / "daemon_state.json"
BOT_TOKEN = "8549153948:AAHfqzF7yxBULVB0KJ0dZQsCOqsSh9xHSkk"
BOT_ID = 8549153948

# Anti-race settings
COOLDOWN_AFTER_CREATE_SECONDS = 15  # Wait 15 seconds after creating a topic before processing
COOLDOWN_AFTER_AUTOTHREAD_SECONDS = 10  # Wait 10 seconds after auto-threading before next check
MIN_MESSAGES_FOR_AUTOTHREAD = 2  # Minimum messages required (bot welcome + user message)
STATE_CLEANUP_AGE_DAYS = 7  # Clean up processed entries older than this

# Forums to monitor (chat_id -> config)
MONITORED_FORUMS = {
    -1003643461316: {
        "name": "Clawd: Conversations",
        "welcome_message": "👋 What's on your mind?",
        "persistent_topics": [1]  # Topic IDs that should NOT be auto-threaded (e.g., "Main" chat)
    }
}

# Global lock to prevent concurrent runs
_daemon_lock = asyncio.Lock()

# Shared client instance for connection reuse
_shared_client = None
_client_lock = asyncio.Lock()

def load_state(path: Path) -> dict:
    """Load state with error handling for corrupted files."""
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[{datetime.now()}] Warning: Failed to load {path}: {e}")
        # Backup corrupted file
        if path.exists():
            backup_path = path.with_suffix('.json.bak')
            try:
                path.rename(backup_path)
                print(f"[{datetime.now()}] Backed up corrupted state to {backup_path}")
            except:
                pass
    return {}

def save_state(path: Path, state: dict):
    """Save state atomically to prevent corruption."""
    tmp_path = path.with_suffix('.json.tmp')
    try:
        with open(tmp_path, "w") as f:
            json.dump(state, f, indent=2)
        tmp_path.replace(path)  # Atomic on POSIX
    except IOError as e:
        print(f"[{datetime.now()}] Error saving state to {path}: {e}")
        if tmp_path.exists():
            tmp_path.unlink()

def get_current_general(chat_id: int) -> int:
    state = load_state(STATE_PATH)
    return state.get(str(chat_id), {}).get("general_topic_id", 1)

def get_daemon_state() -> dict:
    return load_state(DAEMON_STATE_PATH)

def save_daemon_state(state: dict):
    save_state(DAEMON_STATE_PATH, state)

def cleanup_old_state(daemon_state: dict) -> dict:
    """Remove old entries from processed and created_topics to prevent unbounded growth."""
    cutoff = datetime.now() - timedelta(days=STATE_CLEANUP_AGE_DAYS)
    
    for key in ["processed", "created_topics"]:
        if key not in daemon_state:
            continue
        to_remove = []
        for entry_key, entry_data in daemon_state[key].items():
            try:
                ts = datetime.fromisoformat(entry_data.get("timestamp", ""))
                if ts < cutoff:
                    to_remove.append(entry_key)
            except (ValueError, TypeError):
                to_remove.append(entry_key)  # Remove entries with invalid timestamps
        
        for entry_key in to_remove:
            del daemon_state[key][entry_key]
    
    return daemon_state

@asynccontextmanager
async def get_pyrogram_client():
    """Get a shared Pyrogram client with proper lifecycle management."""
    global _shared_client
    
    from pyrogram import Client
    
    async with _client_lock:
        if _shared_client is None or not _shared_client.is_connected:
            config_path = CONFIG_DIR / "config.json"
            if not config_path.exists():
                raise FileNotFoundError(f"Config not found: {config_path}")
            
            config = json.load(open(config_path))
            session_path = CONFIG_DIR / "argon_daemon"
            
            _shared_client = Client(
                str(session_path),
                api_id=config["api_id"],
                api_hash=config["api_hash"]
            )
            await _shared_client.start()
    
    try:
        yield _shared_client
    except Exception as e:
        # On error, disconnect to force fresh connection next time
        print(f"[{datetime.now()}] Client error, will reconnect: {e}")
        async with _client_lock:
            if _shared_client and _shared_client.is_connected:
                try:
                    await _shared_client.stop()
                except:
                    pass
            _shared_client = None
        raise

async def shutdown_client():
    """Cleanly shutdown the shared client."""
    global _shared_client
    async with _client_lock:
        if _shared_client and _shared_client.is_connected:
            await _shared_client.stop()
        _shared_client = None

def get_recent_messages(chat_id: int, topic_id: int, limit: int = 10) -> list:
    """Get recent messages from a topic using the Telegram Bot API."""
    # Note: Bot API doesn't have a direct "get messages from topic" endpoint.
    # We'd need to use getUpdates or MTProto for this.
    # For now, we'll use a workaround - check updates.
    return []

def has_meaningful_content(msg) -> tuple[str, bool, str]:
    """
    Extract content info from a message.
    
    Returns: (text, has_media, media_type)
    """
    # Safely extract text
    raw_text = getattr(msg, 'message', None)
    text = (raw_text[:100] if raw_text else '').strip()
    
    # Check for various media types
    media = getattr(msg, 'media', None)
    has_media = media is not None
    media_type = ""
    
    if has_media:
        # Determine specific media type for better logging
        media_class = type(media).__name__
        if 'Voice' in media_class or 'Audio' in media_class:
            media_type = "voice/audio"
        elif 'Photo' in media_class:
            media_type = "photo"
        elif 'Video' in media_class:
            media_type = "video"
        elif 'Document' in media_class:
            media_type = "document"
        elif 'Sticker' in media_class:
            media_type = "sticker"
        elif 'Animation' in media_class:
            media_type = "animation/gif"
        else:
            media_type = media_class
    
    return text, has_media, media_type

async def check_for_user_message_mtproto(chat_id: int, topic_id: int) -> bool:
    """Check if there's a valid conversation in this topic.
    
    Returns True only if:
    - At least 2 messages total
    - At least 1 bot message (welcome)
    - At least 1 user message AFTER the bot's welcome (with text OR media like voice/photo)
    """
    try:
        async with get_pyrogram_client() as app:
            from pyrogram.raw import functions
            peer = await app.resolve_peer(chat_id)
            
            # Get recent messages from the topic
            result = await app.invoke(
                functions.messages.GetReplies(
                    peer=peer,
                    msg_id=topic_id,  # The topic's root message
                    offset_id=0,
                    offset_date=0,
                    add_offset=0,
                    limit=15,  # Increased limit for better coverage
                    max_id=0,
                    min_id=0,
                    hash=0
                )
            )
            
            # Collect messages with timestamps
            messages = []
            for msg in result.messages:
                if not hasattr(msg, 'from_id') or not hasattr(msg, 'date'):
                    continue
                    
                from_id = getattr(msg.from_id, 'user_id', None)
                if not from_id:
                    continue
                
                text, has_media, media_type = has_meaningful_content(msg)
                
                messages.append({
                    'from_id': from_id,
                    'date': msg.date,
                    'is_bot': from_id == BOT_ID,
                    'text': text,
                    'has_media': has_media,
                    'media_type': media_type,
                    'msg_id': getattr(msg, 'id', 0)
                })
            
            # Sort by date (oldest first)
            messages.sort(key=lambda x: x['date'])
            
            # Need at least 2 messages total
            if len(messages) < MIN_MESSAGES_FOR_AUTOTHREAD:
                print(f"[{datetime.now()}] Topic {topic_id}: only {len(messages)} messages (need {MIN_MESSAGES_FOR_AUTOTHREAD})")
                return False
            
            # Separate bot and user messages
            # User messages MUST have text OR media (voice, photo, video, document, sticker, etc.)
            bot_messages = [m for m in messages if m['is_bot']]
            user_messages = [m for m in messages if not m['is_bot'] and (m['text'] or m['has_media'])]
            
            # Log details for debugging
            user_content_types = []
            for m in user_messages:
                if m['text']:
                    user_content_types.append(f"text({len(m['text'])}ch)")
                if m['has_media']:
                    user_content_types.append(m['media_type'] or 'media')
            
            print(f"[{datetime.now()}] Topic {topic_id}: {len(messages)} msgs total, "
                  f"{len(bot_messages)} bot, {len(user_messages)} user with content: [{', '.join(user_content_types)}]")
            
            # Need at least 1 bot message (welcome) AND 1 user message WITH TEXT OR MEDIA
            if not bot_messages:
                print(f"[{datetime.now()}] Topic {topic_id}: no bot messages found")
                return False
            if not user_messages:
                print(f"[{datetime.now()}] Topic {topic_id}: no user messages with content found")
                return False
            
            # User message must come AFTER bot's welcome message (check first bot message)
            first_bot_time = min(m['date'] for m in bot_messages)
            user_msgs_after_bot = [m for m in user_messages if m['date'] > first_bot_time]
            
            if not user_msgs_after_bot:
                print(f"[{datetime.now()}] Topic {topic_id}: no user message after bot welcome")
                return False
            
            print(f"[{datetime.now()}] ✓ Valid conversation detected in topic {topic_id}: "
                  f"{len(bot_messages)} bot + {len(user_msgs_after_bot)} user msgs after welcome")
            return True
            
    except Exception as e:
        print(f"[{datetime.now()}] Error checking messages in topic {topic_id}: {e}")
        traceback.print_exc()
        return False

async def trigger_auto_thread(chat_id: int, topic_id: int, topic_name: str):
    """Trigger auto-threading for a topic."""
    from auto_thread import auto_thread
    
    result = await auto_thread(
        chat_id=chat_id,
        current_topic_id=topic_id,
        new_topic_name=topic_name
    )
    
    # Send welcome to new General with retry
    new_general_id = result.get("new_general_id")
    if new_general_id:
        forum_config = MONITORED_FORUMS.get(chat_id, {})
        welcome = forum_config.get("welcome_message", "👋 What's on your mind?")
        
        # Retry up to 3 times with exponential backoff
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "message_thread_id": new_general_id,
                        "text": welcome
                    },
                    timeout=10
                )
                if resp.ok:
                    print(f"[{datetime.now()}] Sent welcome to new General (topic {new_general_id})")
                    break
                elif resp.status_code == 429:  # Rate limited
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    print(f"[{datetime.now()}] Rate limited, waiting {retry_after}s...")
                    await asyncio.sleep(retry_after)
                else:
                    print(f"[{datetime.now()}] Failed to send welcome: {resp.text}")
                    break
            except Exception as e:
                print(f"[{datetime.now()}] Welcome send attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
    
    return result

async def generate_topic_name(chat_id: int, topic_id: int) -> str:
    """Generate a smart topic name from conversation content."""
    try:
        async with get_pyrogram_client() as app:
            from pyrogram.raw import functions
            peer = await app.resolve_peer(chat_id)
            
            result = await app.invoke(
                functions.messages.GetReplies(
                    peer=peer,
                    msg_id=topic_id,
                    offset_id=0,
                    offset_date=0,
                    add_offset=0,
                    limit=15,
                    max_id=0,
                    min_id=0,
                    hash=0
                )
            )
            
            # Collect text messages for analysis
            user_texts = []
            bot_texts = []
            has_voice = False
            
            for msg in result.messages:
                from_id = getattr(getattr(msg, 'from_id', None), 'user_id', None)
                text = getattr(msg, 'message', None)
                media = getattr(msg, 'media', None)
                
                # Check for voice messages
                if media and 'Voice' in type(media).__name__:
                    has_voice = True
                
                if text:
                    text = text.strip()
                    if from_id == BOT_ID:
                        bot_texts.append(text)
                    elif from_id:
                        user_texts.append(text)
            
            # Smart title extraction
            
            # 1. Check user messages for clear topic/question
            for text in user_texts:
                clean = text.lower().strip()
                # Skip greetings and short messages
                if clean in ['hi', 'hello', 'hey', 'yo', '?', 'test', 'ok', 'yes', 'no']:
                    continue
                # Questions make good titles
                if '?' in text:
                    q = text.split('?')[0].strip() + '?'
                    if len(q) > 5:  # Avoid "?" alone
                        return q[:35] + ('...' if len(q) > 35 else '')
                # Substantial text
                if len(text) > 10:
                    first = text.split('\n')[0].split('.')[0].strip()
                    if len(first) > 5:
                        return first[:35] + ('...' if len(first) > 35 else '')
            
            # 2. Extract topic from bot response (if substantial)
            for text in bot_texts:
                # Skip welcome messages
                if any(text.lower().startswith(w) for w in ['hey', 'hi', 'hello', '👋', "what's on"]):
                    continue
                # Look for markdown headers or clear topics
                for line in text.split('\n'):
                    line = line.strip()
                    if line.startswith('**') and '**' in line[2:]:
                        topic = line.split('**')[1]
                        if len(topic) > 3:
                            return topic[:35] + ('...' if len(topic) > 35 else '')
                    if len(line) > 15 and ':' in line[:30]:
                        topic = line.split(':')[0].strip()
                        if len(topic) > 5 and not topic.lower().startswith(('http', 'note')):
                            return topic[:35]
            
            # 3. Voice message fallback
            if has_voice and not user_texts:
                return f"Voice chat {datetime.now().strftime('%b %d %H:%M')}"
            
            # 4. Generic fallback
            return f"Chat {datetime.now().strftime('%b %d %H:%M')}"
            
    except Exception as e:
        print(f"[{datetime.now()}] Title generation error: {e}")
        traceback.print_exc()
        return f"Chat {datetime.now().strftime('%b %d %H:%M')}"

async def ensure_general_exists(chat_id: int) -> int:
    """Ensure a General topic exists. Create one if missing/closed."""
    from pyrogram.raw import functions
    
    current_general = get_current_general(chat_id)
    
    try:
        async with get_pyrogram_client() as app:
            peer = await app.resolve_peer(chat_id)
            
            # Check if current General exists and is open
            result = await app.invoke(
                functions.channels.GetForumTopics(
                    channel=peer,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=50
                )
            )
            
            # Build topic lookup
            topics_by_id = {topic.id: topic for topic in result.topics}
            
            # Check current general status
            current_topic = topics_by_id.get(current_general)
            if current_topic and not getattr(current_topic, 'closed', False):
                return current_general  # All good
            
            # Find any open topic named "General" - prefer the NEWEST one (highest ID)
            general_topics = [
                topic for topic in result.topics 
                if getattr(topic, 'title', '') == "General" and not getattr(topic, 'closed', False)
            ]
            
            if general_topics:
                # Use the newest General topic
                general_topic = max(general_topics, key=lambda t: t.id)
                print(f"[{datetime.now()}] Found existing General topic: {general_topic.id}")
                
                # Update state
                state = load_state(STATE_PATH)
                if str(chat_id) not in state:
                    state[str(chat_id)] = {}
                state[str(chat_id)]["general_topic_id"] = general_topic.id
                save_state(STATE_PATH, state)
                return general_topic.id
            
            # Need to create a new General
            print(f"[{datetime.now()}] No open General found, creating one...")
            
            # Generate a unique random_id
            random_id = int.from_bytes(os.urandom(4), 'big')
            
            create_result = await app.invoke(
                functions.channels.CreateForumTopic(
                    channel=peer,
                    title="General",
                    random_id=random_id,
                    icon_color=0x6FB9F0
                )
            )
            
            # Extract new topic ID from the result
            # The result contains Updates with the new topic info
            new_topic_id = None
            
            # Method 1: Check the result directly for topic info
            if hasattr(create_result, 'updates'):
                for update in create_result.updates:
                    if hasattr(update, 'id'):
                        # This might be the message ID in the topic
                        pass
            
            # Method 2: Re-fetch topics and find the newest "General"
            await asyncio.sleep(0.5)  # Brief wait for Telegram to propagate
            
            topics_result = await app.invoke(
                functions.channels.GetForumTopics(
                    channel=peer,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=10
                )
            )
            
            # Find the newest open General topic (should be the one we just created)
            general_topics = [
                topic for topic in topics_result.topics
                if getattr(topic, 'title', '') == "General" and not getattr(topic, 'closed', False)
            ]
            
            if general_topics:
                new_topic = max(general_topics, key=lambda t: t.id)
                new_topic_id = new_topic.id
            
            if new_topic_id:
                print(f"[{datetime.now()}] Created new General: topic {new_topic_id}")
                
                # Update forum state
                state = load_state(STATE_PATH)
                if str(chat_id) not in state:
                    state[str(chat_id)] = {}
                state[str(chat_id)]["general_topic_id"] = new_topic_id
                save_state(STATE_PATH, state)
                
                # Track creation time in daemon_state for anti-race protection
                daemon_state = get_daemon_state()
                if "created_topics" not in daemon_state:
                    daemon_state["created_topics"] = {}
                daemon_state["created_topics"][f"{chat_id}:{new_topic_id}"] = {
                    "timestamp": datetime.now().isoformat(),
                    "source": "ensure_general_exists"
                }
                save_daemon_state(daemon_state)
                
                # Send welcome with retry
                forum_config = MONITORED_FORUMS.get(chat_id, {})
                welcome = forum_config.get("welcome_message", "👋 What's on your mind?")
                
                for attempt in range(3):
                    try:
                        resp = requests.post(
                            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "message_thread_id": new_topic_id,
                                "text": welcome
                            },
                            timeout=10
                        )
                        if resp.ok:
                            break
                        elif resp.status_code == 429:
                            retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                            await asyncio.sleep(retry_after)
                        else:
                            break
                    except Exception as e:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                
                return new_topic_id
            else:
                print(f"[{datetime.now()}] Warning: Created General but couldn't find it")
            
            return current_general  # Fallback
            
    except Exception as e:
        print(f"[{datetime.now()}] Error ensuring General exists: {e}")
        traceback.print_exc()
        return current_general

async def check_and_autothread_forum(chat_id: int):
    """Check a forum and auto-thread if needed."""
    # Use lock to prevent concurrent runs
    async with _daemon_lock:
        return await _check_and_autothread_forum_impl(chat_id)

async def _check_and_autothread_forum_impl(chat_id: int):
    """Internal implementation - must be called with _daemon_lock held."""
    # First ensure General exists
    current_general = await ensure_general_exists(chat_id)
    
    # Skip if current General is a persistent topic (like "Main")
    forum_config = MONITORED_FORUMS.get(chat_id, {})
    persistent_topics = forum_config.get("persistent_topics", [])
    if current_general in persistent_topics:
        return False  # Don't auto-thread persistent topics
    
    daemon_state = get_daemon_state()
    
    # Periodic cleanup of old state entries
    daemon_state = cleanup_old_state(daemon_state)
    
    # Track which topics we've already processed
    processed_key = f"{chat_id}:{current_general}"
    if daemon_state.get("processed", {}).get(processed_key):
        return False  # Already processed this topic
    
    # Anti-race safeguard 1: Check if this topic was recently created
    created_key = f"{chat_id}:{current_general}"
    created_info = daemon_state.get("created_topics", {}).get(created_key)
    if created_info:
        try:
            created_time = datetime.fromisoformat(created_info.get("timestamp", ""))
            age_seconds = (datetime.now() - created_time).total_seconds()
            if age_seconds < COOLDOWN_AFTER_CREATE_SECONDS:
                print(f"[{datetime.now()}] Skipping topic {current_general} - created {age_seconds:.0f}s ago (cooldown: {COOLDOWN_AFTER_CREATE_SECONDS}s)")
                return False
        except (ValueError, TypeError):
            pass
    
    # Anti-race safeguard 2: Check if this topic was created as new_general from auto-threading
    for key, data in daemon_state.get("processed", {}).items():
        if data.get("new_general") == current_general:
            created_at = data.get("timestamp", "")
            if created_at:
                try:
                    created_time = datetime.fromisoformat(created_at)
                    age_seconds = (datetime.now() - created_time).total_seconds()
                    if age_seconds < COOLDOWN_AFTER_CREATE_SECONDS:
                        print(f"[{datetime.now()}] Skipping topic {current_general} - auto-threaded {age_seconds:.0f}s ago (cooldown: {COOLDOWN_AFTER_CREATE_SECONDS}s)")
                        return False
                except (ValueError, TypeError):
                    pass
    
    # Anti-race safeguard 3: Global cooldown after any auto-threading
    last_autothread = daemon_state.get("last_autothread_timestamp")
    if last_autothread:
        try:
            last_time = datetime.fromisoformat(last_autothread)
            age_seconds = (datetime.now() - last_time).total_seconds()
            if age_seconds < COOLDOWN_AFTER_AUTOTHREAD_SECONDS:
                print(f"[{datetime.now()}] Skipping - global cooldown: {age_seconds:.0f}s since last auto-thread (need {COOLDOWN_AFTER_AUTOTHREAD_SECONDS}s)")
                return False
        except (ValueError, TypeError):
            pass
    
    # Check if there's a conversation in current General
    has_conversation = await check_for_user_message_mtproto(chat_id, current_general)
    
    if has_conversation:
        print(f"[{datetime.now()}] Conversation detected in General (topic {current_general})")
        
        # Generate topic name
        topic_name = await generate_topic_name(chat_id, current_general)
        print(f"[{datetime.now()}] Generated name: {topic_name}")
        
        # Trigger auto-threading
        result = await trigger_auto_thread(chat_id, current_general, topic_name)
        print(f"[{datetime.now()}] Auto-threaded: {result}")
        
        # Mark as processed and set global cooldown
        if "processed" not in daemon_state:
            daemon_state["processed"] = {}
        daemon_state["processed"][processed_key] = {
            "timestamp": datetime.now().isoformat(),
            "renamed_to": topic_name,
            "new_general": result.get("new_general_id")
        }
        
        # Also track the new general in created_topics for consistent cooldown handling
        new_general_id = result.get("new_general_id")
        if new_general_id:
            if "created_topics" not in daemon_state:
                daemon_state["created_topics"] = {}
            daemon_state["created_topics"][f"{chat_id}:{new_general_id}"] = {
                "timestamp": datetime.now().isoformat(),
                "source": "auto_thread"
            }
        
        # Set global cooldown timestamp
        daemon_state["last_autothread_timestamp"] = datetime.now().isoformat()
        
        save_daemon_state(daemon_state)
        
        return True
    
    return False

async def run_once():
    """Run a single check across all monitored forums."""
    for chat_id in MONITORED_FORUMS:
        try:
            await check_and_autothread_forum(chat_id)
        except Exception as e:
            print(f"[{datetime.now()}] Error checking {chat_id}: {e}")
            traceback.print_exc()

async def run_daemon(interval: int = 30):
    """Run continuously, checking every interval seconds."""
    print(f"[{datetime.now()}] Auto-threading daemon started (interval: {interval}s)")
    print(f"[{datetime.now()}] Monitoring forums: {list(MONITORED_FORUMS.keys())}")
    print(f"[{datetime.now()}] Settings: create_cooldown={COOLDOWN_AFTER_CREATE_SECONDS}s, "
          f"autothread_cooldown={COOLDOWN_AFTER_AUTOTHREAD_SECONDS}s, min_msgs={MIN_MESSAGES_FOR_AUTOTHREAD}")
    
    try:
        while True:
            try:
                await run_once()
            except Exception as e:
                print(f"[{datetime.now()}] Daemon error: {e}")
                traceback.print_exc()
            
            await asyncio.sleep(interval)
    finally:
        # Clean shutdown
        await shutdown_client()
        print(f"[{datetime.now()}] Daemon shutdown complete")

def main():
    parser = argparse.ArgumentParser(description="Auto-threading daemon")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=30, help="Check interval in seconds")
    
    args = parser.parse_args()
    
    if args.daemon:
        try:
            asyncio.run(run_daemon(args.interval))
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] Interrupted by user")
    elif args.once:
        asyncio.run(run_once())
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
