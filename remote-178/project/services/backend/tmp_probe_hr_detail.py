import app, json
THREAD_ID=243
JOB_THREAD_ID=246
USER_ID=3
with app.db_connect() as conn:
    user = conn.execute("SELECT id, email, name, role, timezone, created_at FROM users WHERE id = ?", (USER_ID,)).fetchone()
    jobs = conn.execute("SELECT id, user_id, name, display_name, status, schedule_kind, days_of_week_json, time_of_day, timezone, next_run_at, last_run_at, last_run_status, last_run_summary, last_error, created_at, updated_at FROM jobs WHERE user_id = ? ORDER BY id DESC LIMIT 20", (USER_ID,)).fetchall()
    job_threads = conn.execute("SELECT id, user_id, job_id, external_job_id, title, preview, thread_kind, updated_at FROM threads WHERE user_id = ? AND thread_kind = 'job' ORDER BY id DESC LIMIT 20", (USER_ID,)).fetchall()
    chat_tasks = conn.execute("SELECT id, thread_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error FROM chat_tasks WHERE thread_id = ? ORDER BY id DESC LIMIT 20", (THREAD_ID,)).fetchall()
    msgs = conn.execute("SELECT id, role, substr(content,1,600) as content, created_at, meta_json FROM messages WHERE thread_id = ? ORDER BY id ASC", (THREAD_ID,)).fetchall()
    job_msgs = conn.execute("SELECT id, role, substr(content,1,600) as content, created_at, meta_json FROM messages WHERE thread_id = ? ORDER BY id ASC", (JOB_THREAD_ID,)).fetchall()
    out={'user':dict(user) if user else None,'jobs':[dict(r) for r in jobs],'job_threads':[dict(r) for r in job_threads],'chat_tasks':[dict(r) for r in chat_tasks],'thread_messages':[dict(r) for r in msgs],'job_thread_messages':[dict(r) for r in job_msgs]}
    if jobs:
        ids=tuple(int(r['id']) for r in jobs)
        q=','.join('?' for _ in ids)
        runs=conn.execute(f"SELECT id, job_id, triggered_by_user_id, trigger_type, status, started_at, finished_at, duration_ms, summary, error_text, delivered_to_json FROM job_runs WHERE job_id IN ({q}) ORDER BY id DESC LIMIT 40", ids).fetchall()
        rec=conn.execute(f"SELECT id, job_id, recipient_type, target_value, label, created_at FROM job_recipients WHERE job_id IN ({q}) ORDER BY id DESC LIMIT 40", ids).fetchall()
        subs=conn.execute(f"SELECT id, job_id, user_id, created_at FROM job_subscriptions WHERE job_id IN ({q}) ORDER BY id DESC LIMIT 40", ids).fetchall()
        out['job_runs']=[dict(r) for r in runs]
        out['job_recipients']=[dict(r) for r in rec]
        out['job_subscriptions']=[dict(r) for r in subs]
    print(json.dumps(out, ensure_ascii=False, default=str))
