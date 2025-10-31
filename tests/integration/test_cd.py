#!/usr/bin/env python3
"""Test /cd command via Telegram API."""

import asyncio
import aiohttp
import os
from dotenv import load_dotenv

async def send_command(command: str):
    """Send command via Telegram Bot API."""
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID"))
    topic_id = 63  # TC TESTS topic

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async with aiohttp.ClientSession() as session:
        data = {
            "chat_id": supergroup_id,
            "message_thread_id": topic_id,
            "text": command
        }

        async with session.post(url, data=data) as resp:
            result = await resp.json()
            print(f"Sent: {command}")
            print(f"Response: {result['ok']}")
            if result['ok']:
                print(f"Message ID: {result['result']['message_id']}")
            return result

async def main():
    """Send /cd command and wait for response."""
    # Send command
    await send_command("/cd")

    # Wait for daemon to process
    print("Waiting for daemon to process...")
    await asyncio.sleep(5)

    print("\nDone! Check Telegram for response.")

if __name__ == "__main__":
    asyncio.run(main())
