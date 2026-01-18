#!/usr/bin/env python3
"""Quick auth - pass code as argument to avoid delays."""
import sys
import asyncio
from pyrogram import Client

API_ID = 39395768
API_HASH = "77defc9ba6e55e7f35c935e20dcd427d"
PHONE = "+41774746870"

async def main():
    app = Client(
        "/home/ubuntu/clawd/skills/telegram-userbot/clawd_userbot",
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE
    )
    
    if len(sys.argv) > 1:
        # Code provided as argument
        code = sys.argv[1]
        app.phone_code = code
    
    async with app:
        me = await app.get_me()
        print(f"✅ Authenticated as: {me.first_name} (@{me.username})")

asyncio.run(main())
