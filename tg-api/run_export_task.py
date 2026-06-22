import requests
import csv
import sys
import json

def main():
    url = "http://localhost:8001/export"
    params = {
        "profile": "experiment_20260620",
        "config": "experiment_20260620"
    }
    output_file = "/home/hermes/telegram_posts_from_15_06.csv"
    
    try:
        print(f"Calling API {url} with params {params}...")
        response = requests.get(url, params=params, timeout=120)
        
        if response.status_code != 200:
            print(f"API returned error status {response.status_code}: {response.text}")
            sys.exit(1)
            
        data = response.json()
        print("API response received successfully.")
        
        messages = data.get('messages', [])
        
        if not messages:
            print("No messages found in the API response.")
            print(f"Response data: {json.dumps(data, indent=2)}")
            return

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['channel', 'date', 'text', 'url'])
            for msg in messages:
                writer.writerow([
                    msg.get('chat', ''),
                    msg.get('date', ''),
                    msg.get('message', ''),
                    msg.get('original_url', '')
                ])
        
        print(f"Successfully saved {len(messages)} posts to {output_file}")

    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the API server at http://localhost:8001. Is it running?")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
