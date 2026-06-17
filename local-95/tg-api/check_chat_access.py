import asyncio
import os
import sys
from telethon import TelegramClient
from app import load_telegram_credentials, resolve_session_path

USAGE = "Usage: python3 check_chat_access.py <profile> <chat_id> [message_id] [limit]"


def parse_int(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid integer: {value}") from exc


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(USAGE)

    profile = sys.argv[1]
    chat_id = parse_int(sys.argv[2])
    message_id = parse_int(sys.argv[3]) if len(sys.argv) >= 4 and sys.argv[3] else None
    limit = parse_int(sys.argv[4]) if len(sys.argv) >= 5 and sys.argv[4] else 10

    api_id, api_hash = load_telegram_credentials()
    session_path = resolve_session_path(profile)

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()
    try:
        authorized = await client.is_user_authorized()
        print(f"authorized={authorized}")
        if not authorized:
            return

        entity = await client.get_entity(chat_id)
        print(f"entity_ok=True")
        print(f"entity_type={type(entity).__name__}")
        print(f"title={getattr(entity, 'title', None)}")

        if message_id is not None:
            msg = await client.get_messages(entity, ids=message_id)
            if msg is None:
                print("message_found=False")
            else:
                text = (msg.message or "").replace("\n", " ")[:300]
                print("message_found=True")
                print(f"message_id={msg.id}")
                print(f"date={msg.date.isoformat() if msg.date else None}")
                print(f"text_preview={text!r}")

        msgs = await client.get_messages(entity, limit=limit)
        print(f"last_count={len(msgs)}")
        for idx, msg in enumerate(msgs, 1):
            text = (msg.message or "").replace("\n", " ")[:200]
            print(f"last_{idx}: id={msg.id} date={msg.date.isoformat() if msg.date else None} text={text!r}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
