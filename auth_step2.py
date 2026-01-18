#!/usr/bin/env python3
"""Step 2: Sign in with the code."""
import sys
import asyncio
import json
from pyrogram import Client

API_ID = 39395768
API_HASH = "77defc9ba6e55e7f35c935e20dcd427d"
PHONE = "+41774746870"
SESSION_PATH = "/home/ubuntu/clawd/skills/telegram-userbot/clawd_userbot"
HASH_FILE = "/home/ubuntu/clawd/skills/telegram-userbot/code_hash.txt"
CONFIG_FILE = "/home/ubuntu/clawd/skills/telegram-userbot/config.json"

async def main():
    if len(sys.argv) < 2:
        print("Usage: python auth_step2.py CODE")
        return
    
    code = sys.argv[1]
    
    with open(HASH_FILE) as f:
        phone_code_hash = f.read().strip()
    
    app = Client(SESSION_PATH, api_id=API_ID, api_hash=API_HASH)
    await app.connect()
    
    try:
        user = await app.sign_in(PHONE, phone_code_hash, code)
        print(f"✅ Authenticated as: {user.first_name} (@{user.username})")
        
        # Save config
        with open(CONFIG_FILE, "w") as f:
            json.dump({"api_id": API_ID, "api_hash": API_HASH}, f, indent=2)
        
        await app.disconnect()
    except Exception as e:
        print(f"❌ Error: {e}")
        await app.disconnect()

asyncio.run(main())
