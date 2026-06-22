import asyncio
from app import export_profile_async

async def main():
    data, status = await export_profile_async(profile='profile_1', config_name='channels_export_20260620', since=None, until_id=None, channel_username=None)
    return data

if __name__ == '__main__':
    data = asyncio.run(main())
    import csv
    with open('/home/hermes/workspace/TG-API/export_20260620.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(['channel', 'date', 'text', 'url'])
        for msg in data['messages']:
            writer.writerow([msg['chat'], msg['date'], msg['message'], msg['original_url']])