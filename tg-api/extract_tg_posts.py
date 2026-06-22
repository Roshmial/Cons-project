import json
import csv
from datetime import datetime

# Input and Output paths
INPUT_FILE = "/home/hermes/workspace/TG-API/runtime/178/archive/telegram_messages.jsonl"
OUTPUT_FILE = "/home/hermes/telegram_posts_from_15_06.csv"

# Filters
TARGET_CHANNELS = {"b1_news", "Axenix_Ru"}
DATE_FROM = datetime(2026, 6, 15)

def process_archive():
    count = 0
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as infile, \
             open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as outfile:
            
            writer = csv.writer(outfile)
            writer.writerow(["channel", "date", "text", "url"])
            
            for line in infile:
                if not line.strip():
                    continue
                
                try:
                    msg = json.loads(line)
                    
                    # Check channel
                    chat = msg.get("chat")
                    if chat not in TARGET_CHANNELS:
                        continue
                    
                    # Check date
                    # The date format in the JSON seems to be ISO 8601: "2026-06-12T15:33:47+00:00"
                    date_str = msg.get("date")
                    if not date_str:
                        continue
                    
                    # Handling potential TZ in ISO string
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    # Remove timezone for comparison if necessary, or just compare
                    if dt.replace(tzinfo=None) < DATE_FROM:
                        continue
                    
                    # Get fields
                    text = msg.get("text", "").replace('\n', ' ') # Flatten for CSV readability
                    url = msg.get("original_url", "")
                    
                    writer.writerow([chat, date_str, text, url])
                    count += 1
                    
                except Exception as e:
                    # Skip malformed lines
                    continue
                    
        print(f"SUCCESS: Processed {count} messages. File saved to {OUTPUT_FILE}")
        
    except FileNotFoundError:
        print(f"ERROR: Input file not found: {INPUT_FILE}")
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    process_archive()
