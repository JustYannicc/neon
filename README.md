# Argon 🔵

**Auto-threading daemon for Telegram forum groups in Clawdbot.**

Argon automatically manages conversation flow in Telegram forums by:
- Detecting when conversations happen in a "General" topic
- Renaming that topic to match the conversation subject
- Creating a fresh "General" topic for new conversations
- Maintaining a persistent "Main" topic that doesn't auto-thread

## Features

- **Auto-threading**: Conversations in General automatically become named topics
- **Persistent Main chat**: A pinned topic that behaves like DMs (cleared with /new)
- **Auto-recovery**: Recreates General if deleted/closed
- **Auto-config**: New forums automatically added to Clawdbot's allowlist
- **Systemd service**: Runs reliably in the background

## Requirements

- [Clawdbot](https://github.com/nicholasareed/clawdbot) installed and configured
- Python 3.10+
- Telegram Bot (configured in Clawdbot)
- Telegram User Account (for MTProto API access)

## Installation

### 1. Clone to Clawdbot workspace

```bash
cd ~/.clawdbot  # or your clawdbot workspace
git clone https://github.com/justyannicc/argon.git skills/argon
cd skills/argon
```

### 2. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install pyrogram tgcrypto requests
```

### 3. Authenticate Telegram User Account

Get API credentials from https://my.telegram.org/apps, then:

```bash
python auth_step1.py --api-id YOUR_ID --api-hash YOUR_HASH
# Enter phone number when prompted
# Enter code sent to Telegram
```

### 4. Configure your forum

Edit `autothread_daemon.py` and add your forum to `MONITORED_FORUMS`:

```python
MONITORED_FORUMS = {
    YOUR_CHAT_ID: {
        "name": "Your Forum Name",
        "welcome_message": "👋 What's on your mind?",
        "persistent_topics": [1]  # Topic IDs that shouldn't auto-thread
    }
}
```

Also update `BOT_TOKEN` with your Clawdbot's Telegram bot token.

### 5. Configure Clawdbot

Add your forum to Clawdbot's config (`~/.clawdbot/clawdbot.json`):

```json
{
  "channels": {
    "telegram": {
      "groups": {
        "YOUR_CHAT_ID": {
          "requireMention": false
        }
      },
      "groupPolicy": "allowlist"
    }
  }
}
```

### 6. Install systemd service

```bash
sudo cp autothread.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autothread
sudo systemctl start autothread
```

### 7. Verify it's running

```bash
sudo systemctl status autothread
journalctl -u autothread -f
```

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    Telegram Forum                        │
├─────────────────────────────────────────────────────────┤
│  📌 Main (persistent)     │  General (auto-threads)     │
│  - Like DMs               │  - User sends message       │
│  - Clear with /new        │  - Bot responds             │
│  - Never auto-threads     │  - Daemon detects convo     │
│                           │  - Renames → creates new    │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│              autothread_daemon.py (every 15s)           │
├─────────────────────────────────────────────────────────┤
│  1. Ensure General exists (create if missing)           │
│  2. Check for user msg + bot response                   │
│  3. If found: rename topic, create new General          │
│  4. Send welcome message to new General                 │
└─────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `autothread_daemon.py` | Main daemon (systemd service) |
| `auto_thread.py` | Core rename/create logic |
| `add_allowed_group.py` | Auto-add forums to Clawdbot config |
| `telegram_groups.py` | Forum/topic management CLI |
| `autothread.service` | systemd unit file |
| `forum_state.json` | Tracks current General topic ID |
| `daemon_state.json` | Tracks processed topics |

## Commands

The daemon runs automatically, but you can also use the CLI:

```bash
# Create a new forum
python telegram_groups.py create-forum "Project Name" --invite-bot @YourBot --folder "FolderName"

# Create a topic manually
python telegram_groups.py create-topic CHAT_ID "Topic Name"

# Manually trigger auto-threading
python auto_thread.py CHAT_ID --name "Topic Name"

# Run daemon once (for testing)
python autothread_daemon.py --once
```

## Auto-Updates

To automatically pull updates:

```bash
# Add to crontab
crontab -e

# Add this line (checks hourly)
0 * * * * cd /path/to/skills/argon && git pull --quiet
```

## Troubleshooting

**Daemon not running:**
```bash
sudo systemctl status autothread
journalctl -u autothread --since "10 minutes ago"
```

**Bot not responding in forum:**
- Check `requireMention: false` in Clawdbot config
- Verify bot has admin rights in the forum
- Disable Privacy Mode in BotFather

**Auto-threading not working:**
- Check `forum_state.json` has correct General topic ID
- Verify daemon is running: `ps aux | grep autothread`
- Check logs: `journalctl -u autothread -f`

## License

MIT
