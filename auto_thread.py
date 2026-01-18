#!/usr/bin/env python3
"""
Auto-threading for Telegram forums.
After a conversation starts in "General", this:
1. Renames the current General topic to a conversation-appropriate name
2. Creates a new "General" topic
3. Returns the new General topic ID

Used by Clawdbot after responding in the General topic.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Optional

# Paths
CONFIG_DIR = Path(__file__).parent
SESSION_PATH = CONFIG_DIR / "argon_daemon"
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_PATH = CONFIG_DIR / "forum_state.json"


def load_telegram_config():
    """Load Telegram API credentials."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def load_forum_state():
    """Load forum state (tracks current General topic ID per forum)."""
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def save_forum_state(state: dict):
    """Save forum state."""
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def get_current_general_topic(chat_id: int) -> int:
    """Get the current General topic ID for a forum. Default is 1."""
    state = load_forum_state()
    return state.get(str(chat_id), {}).get("general_topic_id", 1)


def set_current_general_topic(chat_id: int, topic_id: int):
    """Set the current General topic ID for a forum."""
    state = load_forum_state()
    if str(chat_id) not in state:
        state[str(chat_id)] = {}
    state[str(chat_id)]["general_topic_id"] = topic_id
    save_forum_state(state)


def generate_topic_name(user_message: str, bot_response: str, max_length: int = 40) -> str:
    """Generate a topic name from the conversation content."""
    # Use the first line of user message, cleaned up
    text = user_message.strip()
    
    # Remove common greetings
    text = re.sub(r'^(hi|hello|hey|yo|sup|what\'?s up)[,!?\s]*', '', text, flags=re.IGNORECASE)
    
    # Take first sentence or line
    text = text.split('\n')[0].split('.')[0].strip()
    
    # If too short or empty, try to extract from bot response
    if len(text) < 5:
        # Extract a summary from bot response (first meaningful line)
        for line in bot_response.split('\n'):
            line = line.strip()
            if len(line) > 10 and not line.startswith(('Hey', 'Hi', 'Hello', '👋')):
                text = line
                break
    
    # Truncate and clean
    if len(text) > max_length:
        text = text[:max_length-3] + "..."
    
    return text or "Conversation"


async def auto_thread(
    chat_id: int,
    current_topic_id: int,
    new_topic_name: str,
    bot_welcome_message: str = "👋 What's on your mind?"
) -> dict:
    """
    Perform auto-threading:
    1. Rename current topic to new_topic_name
    2. Create new "General" topic
    3. Send welcome message in new General
    4. Update state
    
    Returns: {"new_general_id": int, "renamed_topic_id": int, "renamed_to": str}
    """
    from pyrogram import Client
    from pyrogram.raw import functions
    
    config = load_telegram_config()
    if not config:
        raise RuntimeError("Telegram not authenticated")
    
    app = Client(
        str(SESSION_PATH),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        peer = await app.resolve_peer(chat_id)
        
        # 1. Rename the current topic
        try:
            await app.invoke(
                functions.channels.EditForumTopic(
                    channel=peer,
                    topic_id=current_topic_id,
                    title=new_topic_name
                )
            )
            print(f"✅ Renamed topic {current_topic_id} to: {new_topic_name}")
        except Exception as e:
            print(f"⚠️ Could not rename topic: {e}")
        
        # 2. Create new "General" topic
        try:
            result = await app.invoke(
                functions.channels.CreateForumTopic(
                    channel=peer,
                    title="General",
                    random_id=int.from_bytes(__import__('os').urandom(4), 'big'),
                    icon_color=0x6FB9F0  # Blue color
                )
            )
            # Extract new topic ID from updates
            new_topic_id = None
            for update in result.updates:
                if hasattr(update, 'message') and hasattr(update.message, 'reply_to'):
                    if hasattr(update.message.reply_to, 'forum_topic') and update.message.reply_to.forum_topic:
                        new_topic_id = update.message.reply_to.reply_to_msg_id
                        break
            
            if not new_topic_id:
                # Fallback: get latest topics and find the new General
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
                    if getattr(topic, 'title', '') == "General" and topic.id != current_topic_id:
                        new_topic_id = topic.id
                        break
            
            print(f"✅ Created new General topic with ID: {new_topic_id}")
        except Exception as e:
            print(f"❌ Could not create new General topic: {e}")
            raise
        
        # 3. Send welcome message in new General (using bot API would be better, but we can use userbot)
        # Actually, Clawdbot should send this, so we'll skip and let Clawdbot handle it
        
        # 4. Update state
        if new_topic_id:
            set_current_general_topic(chat_id, new_topic_id)
        
        return {
            "new_general_id": new_topic_id,
            "renamed_topic_id": current_topic_id,
            "renamed_to": new_topic_name
        }


async def main():
    """CLI interface for testing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Auto-thread in Telegram forum")
    parser.add_argument("chat_id", type=int, help="Forum chat ID")
    parser.add_argument("--topic-id", type=int, help="Current topic ID (default: current General)")
    parser.add_argument("--name", required=True, help="New name for the current topic")
    parser.add_argument("--welcome", default="👋 What's on your mind?", help="Welcome message for new General")
    
    args = parser.parse_args()
    
    topic_id = args.topic_id or get_current_general_topic(args.chat_id)
    
    result = await auto_thread(
        chat_id=args.chat_id,
        current_topic_id=topic_id,
        new_topic_name=args.name,
        bot_welcome_message=args.welcome
    )
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
