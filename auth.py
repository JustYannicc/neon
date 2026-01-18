#!/usr/bin/env python3
"""Authenticate Telegram user account for Argon."""

import asyncio
import argparse
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
SESSION_PATH = Path(__file__).parent / "argon_session"

async def authenticate(api_id: int, api_hash: str):
    from pyrogram import Client
    
    # Save config
    with open(CONFIG_PATH, "w") as f:
        json.dump({"api_id": api_id, "api_hash": api_hash}, f, indent=2)
    
    app = Client(str(SESSION_PATH), api_id=api_id, api_hash=api_hash)
    
    async with app:
        me = await app.get_me()
        print(f"✅ Authenticated as: {me.first_name} (@{me.username})")
        print(f"Session saved to: {SESSION_PATH}.session")

def main():
    parser = argparse.ArgumentParser(description="Authenticate Telegram for Argon")
    parser.add_argument("--api-id", type=int, required=True)
    parser.add_argument("--api-hash", required=True)
    args = parser.parse_args()
    asyncio.run(authenticate(args.api_id, args.api_hash))

if __name__ == "__main__":
    main()
