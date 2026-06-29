import app, json
with app.db_connect() as conn:
    row = conn.execute("SELECT id, job_id, trigger_type, status, started_at, finished_at, summary, error_text, delivered_to_json FROM job_runs WHERE job_id = ? ORDER BY id DESC LIMIT 1", (23,)).fetchone()
    print(json.dumps(dict(row) if row else None, ensure_ascii=False, default=str))
