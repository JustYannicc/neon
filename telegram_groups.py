#!/usr/bin/env python3
"""
Telegram Userbot - Group Management via MTProto
Allows creating groups, forums, topics, and managing folders automatically.

Setup (one-time):
1. Get API credentials from https://my.telegram.org/apps
2. Run: python telegram_groups.py auth --api-id YOUR_ID --api-hash YOUR_HASH
3. Enter the phone code sent to your Telegram

Usage:
  python telegram_groups.py create-forum "Clawd: Project X" --invite-bot @BotUsername
  python telegram_groups.py create-topic GROUP_ID "Topic Name"
  python telegram_groups.py add-to-folder GROUP_ID "Folder Name"
"""

import asyncio
import argparse
import json
import os
from pathlib import Path

# Session and config paths
CONFIG_DIR = Path(__file__).parent
SESSION_PATH = CONFIG_DIR / "clawd_userbot"
CONFIG_PATH = CONFIG_DIR / "config.json"


def load_config():
    """Load API credentials from config."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save API credentials to config."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


async def authenticate(api_id: int, api_hash: str):
    """Authenticate with Telegram (one-time setup)."""
    from pyrogram import Client
    
    save_config({"api_id": api_id, "api_hash": api_hash})
    
    app = Client(
        str(SESSION_PATH),
        api_id=api_id,
        api_hash=api_hash
    )
    
    async with app:
        me = await app.get_me()
        print(f"✅ Authenticated as: {me.first_name} (@{me.username})")
        print(f"Session saved to: {SESSION_PATH}.session")
    
    return True


async def create_forum_group(title: str, invite_bot: str = None, add_to_clawdbot: bool = True):
    """Create a forum-enabled supergroup."""
    from pyrogram import Client
    
    config = load_config()
    if not config:
        print("❌ Not authenticated. Run: python telegram_groups.py auth --api-id X --api-hash Y")
        return None
    
    app = Client(
        str(SESSION_PATH),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        # Create supergroup
        chat = await app.create_supergroup(title)
        print(f"✅ Created supergroup: {title} (ID: {chat.id})")
        
        # Enable forum/topics via raw API
        from pyrogram.raw import functions, types
        try:
            await app.invoke(
                functions.channels.ToggleForum(
                    channel=await app.resolve_peer(chat.id),
                    enabled=True
                )
            )
            print(f"✅ Enabled forum mode")
        except Exception as e:
            print(f"⚠️ Forum mode note: {e}")
        
        # Invite bot if specified
        if invite_bot:
            try:
                await app.add_chat_members(chat.id, invite_bot)
                print(f"✅ Invited {invite_bot} to the group")
            except Exception as e:
                print(f"⚠️ Could not invite bot: {e}")
        
        # Add to Clawdbot allowlist
        if add_to_clawdbot:
            try:
                from add_allowed_group import add_group, trigger_reload
                added = add_group(str(chat.id), title)
                if added:
                    trigger_reload()
                    print(f"✅ Added to Clawdbot allowlist")
            except Exception as e:
                print(f"⚠️ Could not add to Clawdbot allowlist: {e}")
        
        return {"id": chat.id, "title": title}


async def create_topic(chat_id: int, name: str):
    """Create a topic in a forum group."""
    from pyrogram import Client
    
    config = load_config()
    app = Client(
        str(SESSION_PATH),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        from pyrogram.raw import functions, types
        
        result = await app.invoke(
            functions.channels.CreateForumTopic(
                channel=await app.resolve_peer(chat_id),
                title=name,
                random_id=int.from_bytes(os.urandom(4), 'big')
            )
        )
        
        # Extract topic ID from updates
        topic_id = None
        for update in result.updates:
            if hasattr(update, 'id'):
                topic_id = update.id
                break
            elif hasattr(update, 'message') and hasattr(update.message, 'id'):
                topic_id = update.message.id
                break
        
        if topic_id is None:
            # Fallback: get from first update's message_id
            topic_id = result.updates[0].id if hasattr(result.updates[0], 'id') else "unknown"
        
        print(f"✅ Created topic '{name}' (ID: {topic_id}) in chat {chat_id}")
        return {"topic_id": topic_id, "name": name, "chat_id": chat_id}


async def add_to_folder(chat_id: int, folder_name: str):
    """Add a chat to a folder (creates folder if doesn't exist)."""
    from pyrogram import Client
    
    config = load_config()
    app = Client(
        str(SESSION_PATH),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        from pyrogram.raw import functions, types
        
        # Get existing folders
        result = await app.invoke(functions.messages.GetDialogFilters())
        
        # Handle different response types
        filters = result.filters if hasattr(result, 'filters') else result
        
        # Find or create folder
        folder_id = None
        existing_filter = None
        for f in filters:
            if hasattr(f, 'title') and f.title == folder_name:
                folder_id = f.id
                existing_filter = f
                break
        
        if folder_id is None:
            # Create new folder
            new_id = max([f.id for f in filters if hasattr(f, 'id')], default=1) + 1
            await app.invoke(
                functions.messages.UpdateDialogFilter(
                    id=new_id,
                    filter=types.DialogFilter(
                        id=new_id,
                        title=folder_name,
                        pinned_peers=[],
                        include_peers=[await app.resolve_peer(chat_id)],
                        exclude_peers=[],
                        contacts=False,
                        non_contacts=False,
                        groups=True,
                        broadcasts=False,
                        bots=False,
                        exclude_muted=False,
                        exclude_read=False,
                        exclude_archived=False,
                    )
                )
            )
            print(f"✅ Created folder '{folder_name}' and added chat")
        else:
            # Add chat to existing folder
            new_peer = await app.resolve_peer(chat_id)
            include_peers = list(existing_filter.include_peers) + [new_peer]
            await app.invoke(
                functions.messages.UpdateDialogFilter(
                    id=folder_id,
                    filter=types.DialogFilter(
                        id=folder_id,
                        title=folder_name,
                        pinned_peers=list(existing_filter.pinned_peers) if existing_filter.pinned_peers else [],
                        include_peers=include_peers,
                        exclude_peers=list(existing_filter.exclude_peers) if existing_filter.exclude_peers else [],
                        contacts=existing_filter.contacts,
                        non_contacts=existing_filter.non_contacts,
                        groups=existing_filter.groups,
                        broadcasts=existing_filter.broadcasts,
                        bots=existing_filter.bots,
                        exclude_muted=existing_filter.exclude_muted,
                        exclude_read=existing_filter.exclude_read,
                        exclude_archived=existing_filter.exclude_archived,
                    )
                )
            )
            print(f"✅ Added chat to existing folder '{folder_name}'")
        
        return True


async def list_groups():
    """List all groups/chats."""
    from pyrogram import Client
    
    config = load_config()
    app = Client(
        str(SESSION_PATH),
        api_id=config["api_id"],
        api_hash=config["api_hash"]
    )
    
    async with app:
        async for dialog in app.get_dialogs():
            if dialog.chat.type in ["group", "supergroup"]:
                forum = "📂" if getattr(dialog.chat, 'is_forum', False) else "💬"
                print(f"{forum} {dialog.chat.title} (ID: {dialog.chat.id})")


def main():
    parser = argparse.ArgumentParser(description="Telegram Userbot Group Management")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Auth command
    auth_parser = subparsers.add_parser("auth", help="Authenticate with Telegram")
    auth_parser.add_argument("--api-id", type=int, required=True)
    auth_parser.add_argument("--api-hash", required=True)
    
    # Create forum command
    forum_parser = subparsers.add_parser("create-forum", help="Create a forum group")
    forum_parser.add_argument("title", help="Group title")
    forum_parser.add_argument("--invite-bot", help="Bot username to invite")
    forum_parser.add_argument("--folder", help="Folder to add group to")
    forum_parser.add_argument("--no-clawdbot", action="store_true", help="Don't add to Clawdbot allowlist")
    
    # Create topic command
    topic_parser = subparsers.add_parser("create-topic", help="Create a topic in a forum")
    topic_parser.add_argument("chat_id", type=int)
    topic_parser.add_argument("name")
    
    # Add to folder command
    folder_parser = subparsers.add_parser("add-to-folder", help="Add chat to folder")
    folder_parser.add_argument("chat_id", type=int)
    folder_parser.add_argument("folder_name")
    
    # List groups command
    subparsers.add_parser("list", help="List all groups")
    
    args = parser.parse_args()
    
    if args.command == "auth":
        asyncio.run(authenticate(args.api_id, args.api_hash))
    elif args.command == "create-forum":
        result = asyncio.run(create_forum_group(args.title, args.invite_bot, add_to_clawdbot=not args.no_clawdbot))
        if result and args.folder:
            asyncio.run(add_to_folder(result["id"], args.folder))
        if result:
            print(json.dumps(result))
    elif args.command == "create-topic":
        result = asyncio.run(create_topic(args.chat_id, args.name))
        print(json.dumps(result))
    elif args.command == "add-to-folder":
        asyncio.run(add_to_folder(args.chat_id, args.folder_name))
    elif args.command == "list":
        asyncio.run(list_groups())


if __name__ == "__main__":
    main()
