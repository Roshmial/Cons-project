import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = PROJECT_DIR / 'hermes_tg_cron_manifest.json'
HERMES_HOME = Path(os.environ.get('HERMES_HOME', Path.home() / '.hermes'))
SCRIPTS_DIR = HERMES_HOME / 'scripts'
JOBS_PATH = HERMES_HOME / 'cron' / 'jobs.json'


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


def ensure_wrapper_scripts(manifest: dict[str, Any]) -> None:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in manifest['wrappers'].items():
        path = SCRIPTS_DIR / name
        path.write_text(content, encoding='utf-8')


def load_jobs_db() -> dict[str, Any]:
    if not JOBS_PATH.exists():
        return {'jobs': []}
    return json.loads(JOBS_PATH.read_text(encoding='utf-8'))


def save_jobs_db(data: dict[str, Any]) -> None:
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOBS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def find_job(name: str) -> dict[str, Any] | None:
    data = load_jobs_db()
    for job in data.get('jobs', []):
        if job.get('name') == name:
            return job
    return None


def sync_job(job_def: dict[str, Any]) -> tuple[str, str]:
    existing = find_job(job_def['name'])
    if existing:
        cmd = [
            'hermes', 'cron', 'edit', existing['id'],
            '--schedule', job_def['schedule'],
            '--name', job_def['name'],
            '--deliver', job_def['deliver'],
            '--script', job_def['script'],
            '--workdir', job_def['workdir'],
        ]
        if job_def['no_agent']:
            cmd.append('--no-agent')
        else:
            cmd.append('--agent')
            cmd.extend(['--prompt', job_def['prompt']])
            if job_def.get('skills'):
                cmd.append('--clear-skills')
                for skill in job_def['skills']:
                    cmd.extend(['--add-skill', skill])
            else:
                cmd.append('--clear-skills')
        result = run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Не удалось обновить job {job_def['name']}: {result.stderr or result.stdout}")
        return 'updated', existing['id']

    cmd = [
        'hermes', 'cron', 'create', job_def['schedule'],
        '--name', job_def['name'],
        '--deliver', job_def['deliver'],
        '--script', job_def['script'],
        '--workdir', job_def['workdir'],
    ]
    if job_def['no_agent']:
        cmd.append('--no-agent')
    else:
        for skill in job_def.get('skills', []):
            cmd.extend(['--skill', skill])
        cmd.append(job_def['prompt'])
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Не удалось создать job {job_def['name']}: {result.stderr or result.stdout}")
    created = find_job(job_def['name'])
    return 'created', (created or {}).get('id', '')


def patch_enabled_toolsets(job_name: str, enabled_toolsets: list[str] | None) -> None:
    data = load_jobs_db()
    changed = False
    for job in data.get('jobs', []):
        if job.get('name') != job_name:
            continue
        if job.get('enabled_toolsets') != enabled_toolsets:
            job['enabled_toolsets'] = enabled_toolsets
            changed = True
    if changed:
        save_jobs_db(data)


def main() -> int:
    manifest = load_manifest()
    ensure_wrapper_scripts(manifest)
    results: list[dict[str, Any]] = []
    for job_def in manifest['jobs']:
        action, job_id = sync_job(job_def)
        patch_enabled_toolsets(job_def['name'], job_def.get('enabled_toolsets'))
        results.append({
            'name': job_def['name'],
            'action': action,
            'job_id': job_id,
            'enabled_toolsets': job_def.get('enabled_toolsets'),
        })
    print(json.dumps({
        'status': 'ok',
        'manifest': str(MANIFEST_PATH),
        'hermes_home': str(HERMES_HOME),
        'jobs_path': str(JOBS_PATH),
        'scripts_dir': str(SCRIPTS_DIR),
        'results': results,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
