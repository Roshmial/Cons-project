import asyncio
import json
import yaml
import os
from datetime import datetime, timezone
from telethon import TelegramClient

# Use environmental variables or fallback to a mock if needed for testing
# But here we need real ones.
API_ID = int(os.environ.get("TG_API_ID", 0))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION_PATH = "/home/hermes/workspace/TG-API/session/profile_1.session"
CONFIG_PATH = "/home/hermes/workspace/TG-API/channels_experiment_20260618.yml"
OUTPUT_PATH = "/home/hermes/workspace/TG-API/raw_logs/experiment_20260618_full.json"

async def main():
    if API_ID == 0 or not API_HASH:
        print("Error: TG_API_ID or TG_API_HASH not set in environment.")
        return

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    try:
        profile_cfg = config['profiles']['profile_1']
    except KeyError:
        print("Error: profile_1 not found in config.")
        return

    channels = profile_cfg['channels']
    date_from = datetime.strptime(profile_cfg['date_from'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    limit_per_channel = profile_cfg.get('limit_per_channel', 1000)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    
    all_messages = []
    
    try:
        async with TelegramClient(SESSION_PATH, API_ID, API_HASH) as client:
            for channel_info in channels:
                username = channel_info['username']
                print(f"Exporting from {username}...")
                try:
                    entity = await client.get_entity(username)
                    count = 0
                    async for message in client.iter_messages(entity, limit=limit_per_channel):
                        if message.date < date_from:
                            break
                        
                        all_messages.append({
                            "channel": username,
                            "id": message.id,
                            "date": message.date.isoformat(),
                            "text": message.text or "",
                            "views": message.views,
                            "forwards": message.forwards
                        })
                        count += 1
                    print(f"  Exported {count} messages.")
                except Exception as e:
                    print(f"  Failed to export from {username}: {e}")
    except Exception as e:
        print(f"Telethon client error: {e}")
        return

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_messages, f, ensure_ascii=False, indent=2)
    
    print(f"Successfully exported {len(all_messages)} messages to {OUTPUT_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
