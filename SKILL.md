# Telegram Userbot Skill

Automated Telegram group/forum/topic management using MTProto API via Pyrogram.

## What it does
- ✅ Create forum groups automatically
- ✅ Create topics within forums
- ✅ Organize chats into folders
- ✅ Invite bots to groups
- ✅ Full automation - no manual Telegram actions needed

## Setup (one-time)

### 1. Get API credentials
User must visit https://my.telegram.org/apps and create an app to get:
- `api_id` (number)
- `api_hash` (string)

### 2. Authenticate
```bash
cd /home/ubuntu/clawd
source .venv/bin/activate
python skills/telegram-userbot/telegram_groups.py auth --api-id YOUR_ID --api-hash YOUR_HASH
```
User will receive a code on Telegram. Enter it to complete auth.

## Usage

### Create a forum group
```bash
source /home/ubuntu/clawd/.venv/bin/activate
python /home/ubuntu/clawd/skills/telegram-userbot/telegram_groups.py create-forum "Clawd: Project X" --invite-bot @Justyanniccs_Clawdbot --folder "Clawd"
```

### Create a topic in a forum
```bash
python /home/ubuntu/clawd/skills/telegram-userbot/telegram_groups.py create-topic -1001234567890 "research-agent"
```

### Add chat to folder
```bash
python /home/ubuntu/clawd/skills/telegram-userbot/telegram_groups.py add-to-folder -1001234567890 "Clawd"
```

### List all groups
```bash
python /home/ubuntu/clawd/skills/telegram-userbot/telegram_groups.py list
```

## Integration with Clawd

When user says "start new project X":
1. Create forum: `create-forum "Clawd: Project X" --invite-bot @Justyanniccs_Clawdbot --folder "Clawd"`
2. Note the chat_id from output
3. Create initial topic if needed
4. Send first message via Clawdbot's message tool to that chat

When spawning sub-agent for a project:
1. Create topic: `create-topic <chat_id> "<agent-label>"`
2. Route sub-agent output to that topic via message tool with messageThreadId

## Files
- `telegram_groups.py` - Main script
- `config.json` - API credentials (created after auth)
- `clawd_userbot.session` - Pyrogram session (created after auth)
