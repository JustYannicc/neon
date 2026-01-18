#!/usr/bin/env python3
"""Step 1: Send the code request, save the hash."""
import asyncio
import json
from pyrogram import Client

API_ID = 39395768
API_HASH = "77defc9ba6e55e7f35c935e20dcd427d"
PHONE = "+41774746870"
SESSION_PATH = "/home/ubuntu/clawd/skills/telegram-userbot/clawd_userbot"
HASH_FILE = "/home/ubuntu/clawd/skills/telegram-userbot/code_hash.txt"

async def main():
    app = Client(SESSION_PATH, api_id=API_ID, api_hash=API_HASH)
    await app.connect()
    sent = await app.send_code(PHONE)
    with open(HASH_FILE, "w") as f:
        f.write(sent.phone_code_hash)
    print(f"✅ Code sent! Hash saved. Now run auth_step2.py with the code.")
    await app.disconnect()

asyncio.run(main())
