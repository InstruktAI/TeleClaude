#!/usr/bin/env python3
"""Quick script to send file via Telegram adapter."""
import asyncio
from teleclaude.core.db import db
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.config import config

async def main():
    # Get current session
    session_id = "f069ecb4-c5be-4385-916b-4eebbb7771f9"
    session = await db.get_session(session_id)

    if not session:
        print(f"Session {session_id} not found")
        return

    print(f"Found session: {session.title}")

    # Create adapter client
    client = AdapterClient()

    # Create Telegram adapter
    telegram_config = {
        "bot_token": config.telegram.bot_token,
        "supergroup_id": config.telegram.supergroup_id,
        "user_id": config.telegram.user_id,
        "is_master": config.computer.is_master,
    }

    telegram_adapter = TelegramAdapter(client, telegram_config)
    await telegram_adapter.start()

    # Send the file
    file_path = "/Users/Morriz/.claude/projects/-Users-Morriz-Documents-Workspace-morriz-teleclaude/c44886a7-ba1c-43e1-8b48-c12c404f1985.jsonl"
    caption = "Claude session that stopped at 05:20 - notification hook work"

    print(f"Sending file...")
    message_id = await telegram_adapter.send_file(
        session_id=session_id,
        file_path=file_path,
        caption=caption
    )

    print(f"File sent! Message ID: {message_id}")

    await telegram_adapter.stop()

if __name__ == "__main__":
    asyncio.run(main())
