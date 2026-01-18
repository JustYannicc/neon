#!/bin/bash
# Usage: check_and_autothread.sh CHAT_ID TOPIC_ID "TOPIC_NAME"
# If TOPIC_ID matches current General, runs auto-threading and returns new General ID
# Otherwise returns "not_general"

CHAT_ID="$1"
TOPIC_ID="$2"
TOPIC_NAME="$3"

if [ -z "$CHAT_ID" ] || [ -z "$TOPIC_ID" ] || [ -z "$TOPIC_NAME" ]; then
    echo "Usage: check_and_autothread.sh CHAT_ID TOPIC_ID TOPIC_NAME"
    exit 1
fi

cd /home/ubuntu/clawd/skills/telegram-userbot

# Get current General topic ID
CURRENT_GENERAL=$(python3 -c "
import json
from pathlib import Path
state_file = Path('forum_state.json')
if state_file.exists():
    state = json.load(open(state_file))
    print(state.get('$CHAT_ID', {}).get('general_topic_id', 1))
else:
    print(1)
" 2>/dev/null)

# Check if we're in General
if [ "$TOPIC_ID" = "$CURRENT_GENERAL" ]; then
    # We're in General - run auto-threading
    source /home/ubuntu/clawd/.venv/bin/activate
    python auto_thread.py "$CHAT_ID" --topic-id "$TOPIC_ID" --name "$TOPIC_NAME" 2>&1 | tail -1
    
    # Return new General ID
    python3 -c "
import json
state = json.load(open('forum_state.json'))
print(state.get('$CHAT_ID', {}).get('general_topic_id', 1))
"
else
    echo "not_general"
fi
