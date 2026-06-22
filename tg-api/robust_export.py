import os
import requests
import json
import time

# Use current environment
api_id = os.getenv('TG_API_ID')
api_hash = os.getenv('TG_API_HASH')

channels = [
    "yandexcloud", "vkcloud", "cloudru", "softline_ru", "ibs_ru", 
    "crocrussia", "positive_tech", "kaspersky", "cnews_ru", "tadviser", "habr"
]
profile = "profile_1"
config = "channels_experiment_20260618"
raw_logs_dir = "/home/hermes/workspace/TG-API/raw_logs"
os.makedirs(raw_logs_dir, exist_ok=True)

all_messages = []

for channel in channels:
    print(f"Exporting {channel}...")
    url = f"http://localhost:8001/export?profile={profile}&config={config}&channel={channel}"
    try:
        response = requests.get(url, timeout=600)
        if response.status_code == 200:
            data = response.json()
            messages = data.get('messages', [])
            all_messages.extend(messages)
            
            file_path = os.path.join(raw_logs_dir, f"export_channel_{channel}.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Successfully exported {channel}: {len(messages)} messages.")
        else:
            print(f"Failed to export {channel}: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Error exporting {channel}: {e}")
    time.sleep(2)

final_file = "/home/hermes/workspace/TG-API/raw_logs/experiment_20260618_full.json"
with open(final_file, 'w', encoding='utf-8') as f:
    json.dump({
        "profile": profile,
        "config": config,
        "messages": all_messages,
        "count": len(all_messages)
    }, f, ensure_ascii=False, indent=2)

print(f"Combined export saved to {final_file}. Total messages: {len(all_messages)}")
