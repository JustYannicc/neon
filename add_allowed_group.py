#!/usr/bin/env python3
"""Add a Telegram group to Clawdbot's allowlist and trigger reload."""

import json
import argparse
import subprocess
from pathlib import Path

CONFIG_PATH = Path.home() / ".clawdbot" / "clawdbot.json"


def add_group(chat_id: str, label: str = None):
    """Add a group to the Telegram allowlist."""
    # Normalize chat_id (ensure it's a string)
    chat_id = str(chat_id)
    
    # Read current config
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    # Ensure telegram groups section exists
    if "channels" not in config:
        config["channels"] = {}
    if "telegram" not in config["channels"]:
        config["channels"]["telegram"] = {}
    if "groups" not in config["channels"]["telegram"]:
        config["channels"]["telegram"]["groups"] = {}
    
    # Check if already exists
    if chat_id in config["channels"]["telegram"]["groups"]:
        print(f"Group {chat_id} already in allowlist")
        return False
    
    # Add the group with requireMention: false so bot responds to all messages
    group_config = {
        "requireMention": False
    }
    if label:
        group_config["label"] = label
    config["channels"]["telegram"]["groups"][chat_id] = group_config
    
    # Write updated config
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"Added group {chat_id} ({label or 'no label'}) to allowlist")
    return True


def trigger_reload():
    """Signal Clawdbot to reload config."""
    try:
        # Find clawdbot process and send SIGUSR1
        result = subprocess.run(
            ["pkill", "-USR1", "-f", "clawdbot"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("Sent reload signal to Clawdbot")
        else:
            print("Could not send reload signal (Clawdbot might not be running)")
    except Exception as e:
        print(f"Error sending reload signal: {e}")


def main():
    parser = argparse.ArgumentParser(description="Add Telegram group to Clawdbot allowlist")
    parser.add_argument("chat_id", help="Telegram chat ID (e.g., -1003643461316)")
    parser.add_argument("--label", "-l", help="Optional label for the group")
    parser.add_argument("--no-reload", action="store_true", help="Don't trigger config reload")
    
    args = parser.parse_args()
    
    added = add_group(args.chat_id, args.label)
    
    if added and not args.no_reload:
        trigger_reload()


if __name__ == "__main__":
    main()
