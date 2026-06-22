import json
import csv
from datetime import datetime

archive_path = "/home/hermes/workspace/TG-API/runtime/178/archive/telegram_messages.jsonl"
output_csv = "/home/hermes/workspace/TG-API/tg_export_since_15_06.csv"
date_from = datetime.strptime("2026-06-15", "%Y-%m-%d")

channels_to_collect = {"b1_news", "Axenix_Ru"}
results = []

try:
    with open(archive_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            msg = json.loads(line)
            channel = msg.get("chat", "").replace("@", "")
            if channel not in channels_to_collect:
                continue
            
            date_str = msg.get("date", "")
            if not date_str:
                continue
                
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            
            if dt >= date_from:
                text = msg.get("message", "") or msg.get("text", "") or ""
                if not text:
                    continue
                
                url = msg.get("original_url", "")
                
                results.append({
                    "channel": channel,
                    "date": dt.strftime("%Y-%m-%d %H:%M"),
                    "text": text,
                    "url": url
                })
except Exception as e:
    print(f"Error reading archive: {e}")

results.sort(key=lambda x: x["date"])

try:
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["channel", "date", "text", "url"])
        writer.writeheader()
        writer.writerows(results)
    print(f"SUCCESS: Processed {len(results)} messages. File created at {output_csv}")
except Exception as e:
    print(f"Error writing CSV: {e}")
