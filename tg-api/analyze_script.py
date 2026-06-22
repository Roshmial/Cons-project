import json
import os
from datetime import datetime

# Glossary for classification
GLOSSARY = [
    "исследование", "мероприятие", "кейс", "партнерство", 
    "продукт/решение", "реклама услуг", "корпоративная новость", 
    "интервью/комментарий", " вакансия", "обзор рынка", "аналитика", "требует уточнения"
]

def classify_post(text):
    text = text.lower()
    # Simple keyword-based classification for this task
    # In a real scenario, an LLM would be used here.
    if any(word in text for word in ["вебинар", "конференция", "сессия", "мероприятие", "встреча", "событие"]):
        return "мероприятие"
    if any(word in text for word in ["кейс", "результат", "внедрение", "опыт"]):
        return "кейс"
    if any(word in text for word in ["исследование", "анализ", "данные", "статистика"]):
        return "исследование"
    if any(word in text for word in ["партнерство", "сотрудничество", "совместно"]):
        return "партнерство"
    if any(word in text for word in ["продукт", "решение", "платформа", "модуль", "сервис"]):
        return "продукт/решение"
    if any(word in text for word in ["вакансия", "работа", "открыта позиция", "ищем"]):
        return "вакансия"
    if any(word in text for word in ["новость", "назначение", "награда", "премия", "достижение"]):
        return "корпоративная новость"
    if any(word in text for word in ["интервью", "комментарий", "мнение"]):
        return "интервью/комментарий"
    if any(word in text for word in ["рынок", "тренд", "обзор", "динамика"]):
        return "обзор рынка"
    if any(word in text for word in ["аналитика", "прогноз"]):
        return "аналитика"
    if any(word in text for word in ["услуги", "консультации", "заказать"]):
        return "реклама услуг"
    
    return "требует уточнения"

def extract_trends(messages):
    # Placeholder for trend extraction
    trends = []
    common_keywords = ["ИИ", "импортозамещение", "облако", "контейнеризация", "ADC", "SRM", "IPO"]
    for msg in messages:
        text = msg.get("text", "")
        for kw in common_keywords:
            if kw.lower() in text.lower():
                trends.append(kw)
    
    # Count and return top trends
    from collections import Counter
    return [trend for trend, count in Counter(trends).most_common(5)]

def main():
    input_path = "/home/hermes/workspace/TG-API/raw_logs/experiment_20260618_full.json"
    output_report_path = "/home/hermes/workspace/TG-API/analysis_experiment_20260618.md"
    output_json_path = "/home/hermes/workspace/TG-API/analytics_experiment_20260618.json"

    if not os.path.exists(input_path):
        print(f"Input file {input_path} not found. Using fallback for demonstration if available.")
        # If export failed or wasn't run yet, we can't analyze.
        return

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    non_empty_posts = [m for m in data if m.get("text")]
    
    classifications = []
    type_counts = {}

    for post in non_empty_posts:
        post_type = classify_post(post["text"])
        post["type"] = post_type
        classifications.append(post)
        type_counts[post_type] = type_counts.get(post_type, 0) + 1

    trends = extract_trends(non_empty_posts)
    
    # Cases extraction (simple)
    cases = [p["text"] for p in non_empty_posts if p["type"] == "кейс"]

    # Target audience (simple heuristic)
    audience = "IT-директора, руководители по закупкам, специалисты по цифровой трансформации, инвесторы."

    analytics = {
        "type_counts": type_counts,
        "top_trends": trends,
        "cases_count": len(cases),
        "target_audience": audience
    }

    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(analytics, f, ensure_ascii=False, indent=2)

    # Report generation
    report = f"""# Trend Analysis Report - Experiment 20260618

## Summary
- Total messages exported: {len(data)}
- Non-empty posts processed: {len(non_empty_posts)}

## Content Classification
{json.dumps(type_counts, indent=2, ensure_ascii=False)}

## Key Trends
{', '.join(trends)}

## Target Audience
{audience}

## Identified Cases
- Total cases: {len(cases)}
- Examples:
{chr(10).join([f"- {c[:200]}..." for c in cases[:5]])}
"""
    with open(output_report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"Analysis complete. Report saved to {output_report_path} and analytics to {output_json_path}")

if __name__ == "__main__":
    main()
