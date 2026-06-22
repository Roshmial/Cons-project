import json
import os
from collections import Counter
from datetime import datetime

def analyze_logs(file_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = data.get('messages', [])
    if not messages:
        print("No messages found to analyze.")
        return

    print(f"Analyzing {len(messages)} messages...")
    
    # 1. Top Keywords
    all_text = " ".join([m.get('message', '') or '' for m in messages])
    # Simple keyword analysis (could be improved with NLP)
    keywords = ["cloud", "AI", "ИИ", "инфраструктура", "безопасность", "импортозамещение", "GPU", "Kubernetes", "K8s", "OpenStack", "SaaS", "PaaS", "IaaS"]
    keyword_counts = Counter()
    for kw in keywords:
        keyword_counts[kw] = all_text.lower().count(kw.lower())

    print("\n--- Keyword Trends ---")
    for kw, count in keyword_counts.most_common():
        print(f"{kw}: {count}")

    # 2. Channel Distribution
    channel_counts = Counter([m.get('chat', 'unknown') for m in messages])
    print("\n--- Messages per Channel ---")
    for ch, count in channel_counts.most_common():
        print(f"{ch}: {count}")

    # 3. Most active periods
    dates = [m.get('date', '').split('T')[0] for m in messages]
    date_counts = Counter(dates)
    print("\n--- Top Active Dates ---")
    for dt, count in date_counts.most_common(5):
        print(f"{dt}: {count}")

    # 4. Case Identification (example: high engagement messages)
    print("\n--- High Engagement Cases ---")
    high_engagement = [m for m in messages if (m.get('views', 0) or 0) > 5000]
    for m in high_engagement[:5]:
        print(f"[{m.get('chat')}] {m.get('date')} - Views: {m.get('views')} | Text: {m.get('message')[:100]}...")

analyze_logs("/home/hermes/workspace/TG-API/raw_logs/experiment_20260618_full.json")
