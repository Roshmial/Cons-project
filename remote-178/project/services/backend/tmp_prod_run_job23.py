import app, json
JOB_ID = 23
result = app.execute_job(JOB_ID, triggered_by_user_id=3, trigger_type='manual')
out = {
    'job_id': result.get('job_id'),
    'run_id': result.get('run_id'),
    'status': result.get('status'),
    'summary': (result.get('summary') or '')[:400],
    'error_text': result.get('error_text'),
}
print(json.dumps(out, ensure_ascii=False))
