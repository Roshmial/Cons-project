import app
import json

with app.db_connect() as conn:
    rows = conn.execute("SELECT * FROM app.messages WHERE thread_id = ? AND id <= ? ORDER BY id ASC", (242, 997)).fetchall()
    user = conn.execute("SELECT * FROM app.users WHERE id = ?", (3,)).fetchone()
profile = app.user_to_dict(user, app.db_connect())
print('focused', app.should_use_focused_followup_context(rows, {}))
msgs = app.build_focused_followup_messages(rows, profile, 'BI', {}) if app.should_use_focused_followup_context(rows, {}) else None
if msgs:
    print('prompt_preview_start')
    print(msgs[-1]['content'][:1200])
    print('prompt_preview_end')
reply_text, meta = app.call_hermes_api(rows, profile, 'BI', {})
print('reply_start')
print(reply_text[:4000])
print('reply_end')
print('meta', json.dumps({'downstream': meta.get('downstream'), 'model': meta.get('hermes_model')}, ensure_ascii=False))
