import app
text = '''Слайд 1: Титульный  
**Тема презентации:** Бизнес‑интеллект (BI)
**Подготовлено для:** руководства

---  

Слайд 2: Определение BI  
**Бизнес‑интеллект** – это комплекс...

**Ключевые элементы BI:**  
- источники данных
- слой интеграции

---  

Слайд 3: Зачем нужно BI
- Поддержка принятия решений
- Объединение внутренних и внешних данных
'''
blocks = app.parse_document_export_blocks(text)
for b in blocks:
    print(b)
print('SOURCE', app.extract_presentation_source_from_thread(text, 'BI'))
print('PLAN', app.build_presentation_plan(app.extract_presentation_source_from_thread(text, 'BI')))
