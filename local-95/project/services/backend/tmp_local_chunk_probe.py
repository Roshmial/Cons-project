import app
text = '''Слайд 1: Определение BI
- источники данных
- слой интеграции
- слой хранения
- семантический слой
- слой аналитики
- слой визуализации
'''
source = app.extract_presentation_source_from_thread(text, 'BI')
plan = app.build_presentation_plan(source)
print([item.get('title') for item in plan if item.get('kind') == 'content'])
