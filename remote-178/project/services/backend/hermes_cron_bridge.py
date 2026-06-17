from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any


def _resolve_hermes_runtime() -> tuple[Path, Path]:
    env_python = os.getenv("HERMES_WEB_HERMES_PYTHON") or os.getenv("HERMES_PYTHON")
    env_src = os.getenv("HERMES_WEB_HERMES_SRC") or os.getenv("HERMES_SRC")
    candidates: list[tuple[Path, Path]] = []
    if env_python and env_src:
        candidates.append((Path(env_src).expanduser(), Path(env_python).expanduser()))
    elif env_python:
        python_path = Path(env_python).expanduser()
        candidates.append((python_path.parent.parent.parent.parent, python_path))
    elif env_src:
        src_path = Path(env_src).expanduser()
        candidates.append((src_path, src_path / ".venv" / "bin" / "python"))

    candidates.extend([
        (Path("/home/hermes/.hermes/hermes-agent"), Path("/home/hermes/.hermes/hermes-agent/venv/bin/python")),
        (Path("/home/hermes/apps/hermes-agent"), Path("/home/hermes/apps/hermes-agent/.venv/bin/python")),
    ])
    for src_path, python_path in candidates:
        if src_path.exists() and python_path.exists():
            return src_path, python_path
    fallback_src, fallback_python = candidates[0] if candidates else (
        Path("/home/hermes/.hermes/hermes-agent"),
        Path("/home/hermes/.hermes/hermes-agent/venv/bin/python"),
    )
    return fallback_src, fallback_python


HERMES_SRC, HERMES_PYTHON = _resolve_hermes_runtime()


class HermesCronError(RuntimeError):
    pass


def _run(action: str, **payload: Any) -> Any:
    if not HERMES_PYTHON.exists():
        raise HermesCronError(f"Hermes python not found: {HERMES_PYTHON}")
    script = textwrap.dedent(
        """
        import json
        import sys
        from pathlib import Path

        sys.path.insert(0, '/home/hermes/apps/hermes-agent')
        from cron import jobs as cron_jobs

        request = json.loads(sys.stdin.read())
        action = request['action']
        payload = request.get('payload', {})

        if action == 'list':
            result = cron_jobs.list_jobs(True)
        elif action == 'get':
            result = cron_jobs.get_job(payload['job_id'])
        elif action == 'create':
            result = cron_jobs.create_job(**payload)
        elif action == 'update':
            result = cron_jobs.update_job(payload['job_id'], payload['updates'])
        elif action == 'pause':
            result = cron_jobs.pause_job(payload['job_id'])
        elif action == 'resume':
            result = cron_jobs.resume_job(payload['job_id'])
        elif action == 'trigger':
            result = cron_jobs.trigger_job(payload['job_id'])
        elif action == 'remove':
            result = cron_jobs.remove_job(payload['job_id'])
        else:
            raise ValueError(f'Unknown action: {action}')

        print(json.dumps(result, ensure_ascii=False, default=str))
        """
    )
    proc = subprocess.run(
        [str(HERMES_PYTHON), "-c", script],
        input=json.dumps({"action": action, "payload": payload}, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise HermesCronError(stderr or f"Cron helper failed with code {proc.returncode}")
    output = (proc.stdout or "").strip()
    if not output:
        return None
    return json.loads(output)


def list_jobs() -> list[dict[str, Any]]:
    jobs = _run("list") or []
    return jobs if isinstance(jobs, list) else []


def get_job(job_id: str) -> dict[str, Any] | None:
    job = _run("get", job_id=job_id)
    return job if isinstance(job, dict) else None


def create_job(*, prompt: str, schedule: str, name: str, deliver: str = "local") -> dict[str, Any]:
    job = _run("create", prompt=prompt, schedule=schedule, name=name, deliver=deliver)
    if not isinstance(job, dict):
        raise HermesCronError("Failed to create Hermes cron job")
    return job


def update_job(job_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    job = _run("update", job_id=job_id, updates=updates)
    return job if isinstance(job, dict) else None


def pause_job(job_id: str) -> dict[str, Any] | None:
    job = _run("pause", job_id=job_id)
    return job if isinstance(job, dict) else None


def resume_job(job_id: str) -> dict[str, Any] | None:
    job = _run("resume", job_id=job_id)
    return job if isinstance(job, dict) else None


def trigger_job(job_id: str) -> dict[str, Any] | None:
    job = _run("trigger", job_id=job_id)
    return job if isinstance(job, dict) else None


def remove_job(job_id: str) -> bool:
    return bool(_run("remove", job_id=job_id))


def _description(job: dict[str, Any]) -> str:
    script = str(job.get("script") or "").strip()
    prompt = str(job.get("prompt") or "").strip()
    if script:
        return f"Hermes cron script: {script}"
    if prompt:
        one_line = " ".join(prompt.split())
        return one_line[:220]
    return "Hermes cron job"


def _visibility(job: dict[str, Any]) -> str:
    return "private"


def _status(job: dict[str, Any]) -> str:
    state = str(job.get("state") or "").strip().lower()
    enabled = bool(job.get("enabled", True))
    if state == "paused" or not enabled:
        return "paused"
    return "active"


def _schedule_kind(job: dict[str, Any]) -> str:
    kind = str((job.get("schedule") or {}).get("kind") or "").strip().lower()
    mapping = {
        "cron": "daily",
        "interval": "daily",
        "once": "daily",
    }
    return mapping.get(kind, "daily")


def _pseudo_runs(job: dict[str, Any]) -> list[dict[str, Any]]:
    if not job.get("last_run_at"):
        return []
    return [{
        "id": f"{job.get('id')}:last",
        "status": job.get("last_status") or "unknown",
        "trigger_type": "hermes-cron",
        "started_at": job.get("last_run_at"),
        "finished_at": job.get("last_run_at"),
        "summary": job.get("last_error") or "Последний запуск зафиксирован Hermes",
        "result_text": "",
        "error_text": job.get("last_error") or "",
        "triggered_by_name": "Hermes",
    }]


def _deliver_recipients(job: dict[str, Any]) -> list[dict[str, Any]]:
    deliver_raw = str(job.get("deliver") or "origin").strip()
    targets = [item.strip() for item in deliver_raw.split(",") if item and item.strip()]
    if not targets:
        targets = ["origin"]
    recipients: list[dict[str, Any]] = []
    origin = job.get("origin") or {}
    origin_chat_name = str(origin.get("chat_name") or "").strip()
    origin_platform = str(origin.get("platform") or "").strip()
    origin_chat_id = str(origin.get("chat_id") or "").strip()
    origin_thread_id = str(origin.get("thread_id") or "").strip()
    for target in targets:
        label = target
        note = ""
        if target == "local":
            label = "Локально, без отправки в чат"
            note = "Результат сохраняется локально и не отправляется в подключённый чат."
        elif target == "origin":
            label = origin_chat_name or "Исходный чат запуска"
            note = f"{origin_platform}:{origin_chat_id}" if origin_platform and origin_chat_id else "Исходный чат запуска"
            if origin_thread_id and origin_thread_id.lower() != "none":
                note += f" · thread {origin_thread_id}"
        elif ":" in target:
            label = target
            note = "Явно заданный deliver target Hermes"
        else:
            label = target
            note = "Home-чат подключённой платформы"
        recipients.append({
            "recipient_type": "delivery_target",
            "target_value": target,
            "label": label,
            "note": note,
        })
    return recipients


def to_web_job(job: dict[str, Any], *, include_details: bool = False, recipients: list[dict[str, Any]] | None = None, read_only: bool = True) -> dict[str, Any]:
    schedule_display = str(job.get("schedule_display") or "—")
    next_run = job.get("next_run_at")
    effective_recipients = recipients if recipients is not None else _deliver_recipients(job)
    parameters = {
        "deliver": job.get("deliver"),
        "script": job.get("script"),
        "skills": ", ".join(job.get("skills") or []),
        "profile": job.get("profile"),
        "workdir": job.get("workdir"),
        "toolsets": ", ".join(job.get("enabled_toolsets") or []),
        "no_agent": "yes" if job.get("no_agent") else "no",
    }
    parameters = {k: v for k, v in parameters.items() if v not in (None, "", [])}
    item = {
        "id": str(job.get("id") or ""),
        "name": str(job.get("name") or job.get("id") or "Hermes cron"),
        "description": _description(job),
        "job_type": "custom",
        "visibility": _visibility(job),
        "status": _status(job),
        "schedule_kind": _schedule_kind(job),
        "days_of_week": [],
        "time_of_day": "",
        "start_date": str(job.get("created_at") or "")[:10],
        "timezone": "",
        "prompt_template": str(job.get("prompt") or ""),
        "deliver": job.get("deliver") or "origin",
        "parameters": parameters,
        "next_run_at": next_run,
        "next_runs_preview": [next_run] if next_run else [],
        "last_run_at": job.get("last_run_at"),
        "last_run_status": job.get("last_status"),
        "last_run_summary": job.get("last_error") or "",
        "last_error": job.get("last_error"),
        "schedule_summary": schedule_display,
        "owner": {"id": "hermes", "name": "Hermes", "email": "system@local"},
        "role": "admin",
        "subscriber_count": 0,
        "recipients_count": len(effective_recipients),
        "created_at": job.get("created_at"),
        "updated_at": job.get("last_run_at") or job.get("created_at"),
        "source_of_truth": "hermes_cron",
        "read_only": read_only,
    }
    if include_details:
        item["access"] = [{"user_id": None, "role": "admin", "name": "Администраторы", "email": "admin-only"}]
        item["recipients"] = effective_recipients
        item["runs"] = _pseudo_runs(job)
    return item
