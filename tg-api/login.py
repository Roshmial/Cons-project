import os
import asyncio
from telethon import TelegramClient

# === Настройки API ===
API_ID_RAW = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
if not API_ID_RAW or not API_HASH:
    raise RuntimeError("TG_API_ID and TG_API_HASH must be set in environment")
API_ID = int(API_ID_RAW)

# Профиль, как в profiles[..].session_name
PROFILE = os.environ.get("PROFILE", "profile_1")

# Явная рабочая папка проекта для запуска через Hermes.
# Важно: сессия должна создаваться именно здесь, чтобы app.py использовал тот же файл.
PROJECT_DIR = os.environ.get(
    "TG_API_PROJECT_DIR",
    os.path.dirname(os.path.abspath(__file__)),
)
SESSION_DIR = os.path.join(PROJECT_DIR, "session")
LEGACY_SESSION_ROOTS = [
    PROJECT_DIR,
    os.path.join(os.path.dirname(PROJECT_DIR), "workspace", "TG-API"),
]

os.makedirs(SESSION_DIR, exist_ok=True)
SESSION_PATH = os.path.join(SESSION_DIR, f"{PROFILE}.session")


def cleanup_legacy_session_files(profile: str) -> None:
    archive_dir = os.path.join(SESSION_DIR, "_archive_legacy")
    os.makedirs(archive_dir, exist_ok=True)
    seen = set()
    for root in LEGACY_SESSION_ROOTS:
        for candidate in [
            os.path.join(root, f"{profile}.session"),
            os.path.join(root, "session", f"{profile}.session"),
        ]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if not os.path.exists(candidate) or os.path.abspath(candidate) == os.path.abspath(SESSION_PATH):
                continue
            archived = os.path.join(archive_dir, f"{os.path.basename(os.path.dirname(candidate)) or 'root'}__{os.path.basename(candidate)}")
            if not os.path.exists(archived):
                os.replace(candidate, archived)


async def main():
    cleanup_legacy_session_files(PROFILE)
    print(f"Using profile: {PROFILE}")
    print(f"Session path: {SESSION_PATH}")

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        print("Already authorized, session is valid.")
        await client.disconnect()
        return

    phone = input("Phone (in international format, e.g. +7999...): ")
    await client.send_code_request(phone)
    code = input("Code from Telegram: ")

    try:
        await client.sign_in(phone, code)
    except Exception as e:
        from getpass import getpass
        print(f"2FA or other step required: {e}")
        password = getpass("Password (2FA): ")
        await client.sign_in(password=password)

    print("Logged in successfully, session saved to:", SESSION_PATH)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())