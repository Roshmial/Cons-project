import json
import csv
from datetime import datetime

input_file = '/home/hermes/workspace/TG-API/runtime/178/archive/telegram_messages.jsonl'
output_file = '/home/hermes/workspace/TG-API/tg_export_since_15_06.csv'
target_channels = {'b1_news', 'Axenix_Ru'}
start_date_str = '2026-06-15'

extracted_data = []

with open(input_file, 'r', encoding='utf-8') as f:
    for line in f:
        if not line.strip():
            continue
        try:
            # JSONL might have prefixing line numbers like '1|...'
            # Let's handle that if it exists
            line_content = line.strip()
            if '|' in line_content:
                line_content = line_content.split('|', 1)[1]

            item = json.loads(line_content)
            
            # Filter by channel
            chat = item.get('chat')
            if chat not in target_channels:
                continue
            
            # Filter by date
            date_str = item.get('date')
            if not date_str:
                continue
            
            # date_str is "2026-06-15T00:00:00+00:00"
            # Comparing as strings works for ISO format
            if date_str < start_date_str:
                continue
            
            # Filter by non-empty text
            text = item.get('message') or item.get('text')
            if not text or not text.strip():
                continue
            
            # Mapping
            extracted_data.append({
                'channel': chat,
                'date': date_str,
                'text': text,
                'url': item.get('original_url')
            })
        except (json.JSONDecodeError, ValueError, IndexError) as e:
            # Silently skip if line is not valid JSON after split
            continue

# Write to CSV
fields = ['channel', 'date', 'text', 'url']
with open(output_file, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(extracted_data)

print(f"Successfully extracted {len(extracted_data)} rows to {output_file}")
