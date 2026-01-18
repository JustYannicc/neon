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
from datetime import datetime

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

def load_state(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_state(path: Path, state: dict):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)

def get_current_general(chat_id: int) -> int:
    state = load_state(STATE_PATH)
    return state.get(str(chat_id), {}).get("general_topic_id", 1)

def get_daemon_state() -> dict:
    return load_state(DAEMON_STATE_PATH)

def save_daemon_state(state: dict):
    save_state(DAEMON_STATE_PATH, state)

def get_recent_messages(chat_id: int, topic_id: int, limit: int = 10) -> list:
    """Get recent messages from a topic using the Telegram Bot API."""
    # Note: Bot API doesn't have a direct "get messages from topic" endpoint.
    # We'd need to use getUpdates or MTProto for this.
    # For now, we'll use a workaround - check updates.
    return []

async def check_for_user_message_mtproto(chat_id: int, topic_id: int) -> bool:
    """Check if there's a valid conversation in this topic.
    
    Returns True only if:
    - At least 2 messages total
    - At least 1 bot message (welcome)
    - At least 1 user message AFTER the bot's welcome
    """
    from pyrogram import Client
    
    config_path = CONFIG_DIR / "config.json"
    if not config_path.exists():
        return False
    
    config = json.load(open(config_path))
    session_path = CONFIG_DIR / "argon_daemon"
    
    app = Client(
        str(session_path),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        from pyrogram.raw import functions
        peer = await app.resolve_peer(chat_id)
        
        # Get recent messages from the topic
        try:
            result = await app.invoke(
                functions.messages.GetReplies(
                    peer=peer,
                    msg_id=topic_id,  # The topic's root message
                    offset_id=0,
                    offset_date=0,
                    add_offset=0,
                    limit=10,
                    max_id=0,
                    min_id=0,
                    hash=0
                )
            )
            
            # Collect messages with timestamps
            messages = []
            for msg in result.messages:
                if hasattr(msg, 'from_id') and hasattr(msg, 'date'):
                    from_id = getattr(msg.from_id, 'user_id', None)
                    if from_id:
                        # Safely extract text - handle None and empty cases
                        raw_text = getattr(msg, 'message', None)
                        text = (raw_text[:50] if raw_text else '').strip()
                        
                        # Check for media (voice, photo, video, document, sticker, etc.)
                        has_media = hasattr(msg, 'media') and msg.media is not None
                        
                        messages.append({
                            'from_id': from_id,
                            'date': msg.date,
                            'is_bot': from_id == BOT_ID,
                            'text': text,  # Already stripped, empty string if no text
                            'has_media': has_media  # Voice messages, photos, etc.
                        })
            
            # Sort by date (oldest first)
            messages.sort(key=lambda x: x['date'])
            
            # Need at least 2 messages total
            if len(messages) < 2:
                return False
            
            # Separate bot and user messages (user messages MUST have text OR media like voice/photo)
            bot_messages = [m for m in messages if m['is_bot']]
            user_messages = [m for m in messages if not m['is_bot'] and (len(m.get('text', '')) > 0 or m.get('has_media', False))]
            
            print(f"[{datetime.now()}] Topic {topic_id}: {len(messages)} msgs, {len(bot_messages)} bot, {len(user_messages)} user (with text/media)")
            
            # Need at least 1 bot message (welcome) AND 1 user message WITH TEXT OR MEDIA
            if not bot_messages or not user_messages:
                print(f"[{datetime.now()}] Topic {topic_id}: no valid conversation (bot={len(bot_messages)}, user_with_content={len(user_messages)})")
                return False
            
            # User message must come AFTER bot's welcome message
            first_bot_time = min(m['date'] for m in bot_messages)
            user_after_bot = any(m['date'] > first_bot_time for m in user_messages)
            
            if not user_after_bot:
                return False  # User message came before bot welcome (shouldn't happen)
            
            print(f"[{datetime.now()}] Valid conversation: {len(bot_messages)} bot + {len(user_messages)} user msgs in topic {topic_id}")
            return True
            
        except Exception as e:
            print(f"[{datetime.now()}] Error checking messages: {e}")
            return False

async def trigger_auto_thread(chat_id: int, topic_id: int, topic_name: str):
    """Trigger auto-threading for a topic."""
    from auto_thread import auto_thread
    
    result = await auto_thread(
        chat_id=chat_id,
        current_topic_id=topic_id,
        new_topic_name=topic_name
    )
    
    # Send welcome to new General
    new_general_id = result.get("new_general_id")
    if new_general_id:
        forum_config = MONITORED_FORUMS.get(chat_id, {})
        welcome = forum_config.get("welcome_message", "👋 What's on your mind?")
        
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "message_thread_id": new_general_id,
                "text": welcome
            }
        )
        print(f"[{datetime.now()}] Sent welcome to new General (topic {new_general_id})")
    
    return result

async def generate_topic_name(chat_id: int, topic_id: int) -> str:
    """Generate a smart topic name from conversation content."""
    from pyrogram import Client
    
    config_path = CONFIG_DIR / "config.json"
    config = json.load(open(config_path))
    session_path = CONFIG_DIR / "argon_daemon"
    
    app = Client(
        str(session_path),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        from pyrogram.raw import functions
        peer = await app.resolve_peer(chat_id)
        
        try:
            result = await app.invoke(
                functions.messages.GetReplies(
                    peer=peer,
                    msg_id=topic_id,
                    offset_id=0,
                    offset_date=0,
                    add_offset=0,
                    limit=10,
                    max_id=0,
                    min_id=0,
                    hash=0
                )
            )
            
            # Collect text messages for analysis
            user_texts = []
            bot_texts = []
            
            for msg in result.messages:
                text = getattr(msg, 'message', None)
                if text:
                    from_id = getattr(getattr(msg, 'from_id', None), 'user_id', None)
                    if from_id == BOT_ID:
                        bot_texts.append(text.strip())
                    elif from_id:
                        user_texts.append(text.strip())
            
            # Smart title extraction
            # 1. Check user messages for clear topic/question
            for text in user_texts:
                clean = text.lower().strip()
                # Skip greetings
                if clean in ['hi', 'hello', 'hey', 'yo', '?', 'test']:
                    continue
                # Questions make good titles
                if '?' in text:
                    q = text.split('?')[0].strip() + '?'
                    return q[:35] + ('...' if len(q) > 35 else '')
                # Substantial text
                if len(text) > 10:
                    first = text.split('\n')[0].split('.')[0].strip()
                    if len(first) > 5:
                        return first[:35] + ('...' if len(first) > 35 else '')
            
            # 2. Extract topic from bot response
            for text in bot_texts:
                if text.lower().startswith(('hey', 'hi', 'hello', '👋')):
                    continue
                # Look for markdown headers or clear topics
                for line in text.split('\n'):
                    line = line.strip()
                    if line.startswith('**') and '**' in line[2:]:
                        topic = line.split('**')[1]
                        return topic[:35] + ('...' if len(topic) > 35 else '')
                    if len(line) > 15 and ':' in line[:30]:
                        topic = line.split(':')[0].strip()
                        if len(topic) > 5:
                            return topic[:35]
            
            # 3. Fallback
            return f"Chat {datetime.now().strftime('%b %d %H:%M')}"
            
        except Exception as e:
            print(f"[{datetime.now()}] Title generation error: {e}")
            return f"Chat {datetime.now().strftime('%b %d %H:%M')}"

async def ensure_general_exists(chat_id: int) -> int:
    """Ensure a General topic exists. Create one if missing/closed."""
    from pyrogram import Client
    from pyrogram.raw import functions
    
    config_path = CONFIG_DIR / "config.json"
    config = json.load(open(config_path))
    session_path = CONFIG_DIR / "argon_daemon"
    
    current_general = get_current_general(chat_id)
    
    app = Client(
        str(session_path),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        peer = await app.resolve_peer(chat_id)
        
        # Check if current General exists and is open
        try:
            result = await app.invoke(
                functions.channels.GetForumTopics(
                    channel=peer,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=50
                )
            )
            
            # Find topic with matching ID
            topic_exists = False
            topic_closed = False
            for topic in result.topics:
                if topic.id == current_general:
                    topic_exists = True
                    topic_closed = getattr(topic, 'closed', False)
                    break
            
            # Also check for any topic named "General" - prefer the NEWEST one (highest ID)
            general_topics = [
                topic for topic in result.topics 
                if getattr(topic, 'title', '') == "General" and not getattr(topic, 'closed', False)
            ]
            general_topic = max(general_topics, key=lambda t: t.id) if general_topics else None
            
            if topic_exists and not topic_closed:
                return current_general  # All good
            
            if general_topic:
                # Found an open General topic, use it
                print(f"[{datetime.now()}] Found existing General topic: {general_topic.id}")
                state = load_state(STATE_PATH)
                if str(chat_id) not in state:
                    state[str(chat_id)] = {}
                state[str(chat_id)]["general_topic_id"] = general_topic.id
                save_state(STATE_PATH, state)
                return general_topic.id
            
            # Need to create a new General
            print(f"[{datetime.now()}] No open General found, creating one...")
            
            new_result = await app.invoke(
                functions.channels.CreateForumTopic(
                    channel=peer,
                    title="General",
                    random_id=int.from_bytes(os.urandom(4), 'big'),
                    icon_color=0x6FB9F0
                )
            )
            
            # Extract new topic ID
            new_topic_id = None
            topics_result = await app.invoke(
                functions.channels.GetForumTopics(
                    channel=peer,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=10
                )
            )
            for topic in topics_result.topics:
                if getattr(topic, 'title', '') == "General" and not getattr(topic, 'closed', False):
                    new_topic_id = topic.id
                    break
            
            if new_topic_id:
                print(f"[{datetime.now()}] Created new General: topic {new_topic_id}")
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
                
                # Send welcome
                forum_config = MONITORED_FORUMS.get(chat_id, {})
                welcome = forum_config.get("welcome_message", "👋 What's on your mind?")
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "message_thread_id": new_topic_id,
                        "text": welcome
                    }
                )
                
                return new_topic_id
            
            return current_general  # Fallback
            
        except Exception as e:
            print(f"[{datetime.now()}] Error ensuring General exists: {e}")
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
    
    # Track which topics we've already processed
    processed_key = f"{chat_id}:{current_general}"
    if daemon_state.get("processed", {}).get(processed_key):
        return False  # Already processed this topic
    
    # Anti-race safeguard 1: Check if this topic was recently created by ensure_general_exists
    created_key = f"{chat_id}:{current_general}"
    created_info = daemon_state.get("created_topics", {}).get(created_key)
    if created_info:
        try:
            created_time = datetime.fromisoformat(created_info.get("timestamp", ""))
            age_seconds = (datetime.now() - created_time).total_seconds()
            if age_seconds < COOLDOWN_AFTER_CREATE_SECONDS:
                print(f"[{datetime.now()}] Skipping topic {current_general} - created {age_seconds:.0f}s ago (cooldown: {COOLDOWN_AFTER_CREATE_SECONDS}s)")
                return False
        except:
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
                except:
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
        except:
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

async def run_daemon(interval: int = 30):
    """Run continuously, checking every interval seconds."""
    print(f"[{datetime.now()}] Auto-threading daemon started (interval: {interval}s)")
    print(f"[{datetime.now()}] Monitoring forums: {list(MONITORED_FORUMS.keys())}")
    
    while True:
        try:
            await run_once()
        except Exception as e:
            print(f"[{datetime.now()}] Daemon error: {e}")
        
        await asyncio.sleep(interval)

def main():
    parser = argparse.ArgumentParser(description="Auto-threading daemon")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=30, help="Check interval in seconds")
    
    args = parser.parse_args()
    
    if args.daemon:
        asyncio.run(run_daemon(args.interval))
    elif args.once:
        asyncio.run(run_once())
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
