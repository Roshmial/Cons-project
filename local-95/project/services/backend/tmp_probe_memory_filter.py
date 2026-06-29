import os, tempfile
os.environ['HERMES_WEB_MODE']='mock-hermes'
os.environ['HERMES_WEB_SCHEDULER_ENABLED']='0'
os.environ['HERMES_WEB_ENABLE_DEMO_DATA']='0'
tmpdir=tempfile.mkdtemp(prefix='probe_mem_')
os.environ['HERMES_WEB_BACKEND_DATA_DIR']=tmpdir
os.environ['HERMES_WEB_BACKEND_DB_PATH']=tmpdir + '/probe.duckdb'
import app
samples = [
    'Пользователь предпочитает структурированные дайджесты отраслевых новостей',
    'Предпочитает короткие ответы по делу',
    'Роль агента — ИТ-архитектор и консультант',
    'Пользователь отслеживает рынок LegalAI и новости в Telegram-каналах',
    'Предпочитает CSV с полями: дата, канал, ссылка, summary',
    'Вместо длинной преамбулы сразу отвечай по сути',
]
for s in samples:
    print(app.is_allowed_interaction_memory_item(s), ' | ', s)
print(app.normalize_memory_items(samples))
