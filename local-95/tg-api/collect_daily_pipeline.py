import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from telegram_monitor_pipeline import latest_file, write_collection_report
from tg_monitor_settings import DEFAULT_CONFIG_NAME, DEFAULT_PROFILE_NAME

BASE_DIR = Path(__file__).resolve().parent
ENSURE_API = BASE_DIR / "ensure_api.py"
MONITOR_CLIENT = BASE_DIR / "monitor_client.py"


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=BASE_DIR, text=True, capture_output=True)


def extract_json(stdout: str) -> Dict[str, Any]:
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise ValueError(f"Не удалось найти JSON в stdout: {stdout}")


def verify_fresh_path(path_str: str, started_at: datetime) -> Dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Ожидаемый файл не создан: {path}")
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return {
        "path": str(path),
        "exists": True,
        "is_fresh": modified_at >= started_at,
        "modified_at": modified_at.isoformat(),
    }


def main() -> int:
    started_at = datetime.now(timezone.utc)
    report: Dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "status": "started",
    }

    ensure_result = run_command([sys.executable, str(ENSURE_API)])
    report["ensure_api"] = {
        "exit_code": ensure_result.returncode,
        "stdout": ensure_result.stdout.strip(),
        "stderr": ensure_result.stderr.strip(),
    }
    if ensure_result.returncode != 0:
        report["status"] = "api_failed"
        report_path = write_collection_report(report)
        print(json.dumps({"status": report["status"], "report_path": str(report_path)}, ensure_ascii=False))
        return 1

    collect_result = run_command([
        sys.executable,
        str(MONITOR_CLIENT),
        "--config",
        DEFAULT_CONFIG_NAME,
        "--profile",
        DEFAULT_PROFILE_NAME,
    ])
    report["monitor_client"] = {
        "exit_code": collect_result.returncode,
        "stdout": collect_result.stdout.strip(),
        "stderr": collect_result.stderr.strip(),
    }
    if collect_result.returncode != 0:
        report["status"] = "collector_failed"
        report_path = write_collection_report(report)
        print(json.dumps({"status": report["status"], "report_path": str(report_path)}, ensure_ascii=False))
        return 1

    payload = extract_json(collect_result.stdout)
    report["collector_payload"] = payload

    if payload.get("status") == "no_new_messages":
        report["status"] = "no_new_messages"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report_path = write_collection_report(report)
        print(json.dumps({
            "status": report["status"],
            "report_path": str(report_path),
            "non_empty_messages": 0,
        }, ensure_ascii=False))
        return 0

    raw_check = verify_fresh_path(payload["raw_log"], started_at)
    summary_check = verify_fresh_path(payload["summary_input"], started_at)
    archive_check = verify_fresh_path(payload["archive"], started_at)

    summary_payload = json.loads(Path(payload["summary_input"]).read_text(encoding="utf-8"))
    report["artifact_checks"] = {
        "raw_log": raw_check,
        "summary_input": summary_check,
        "archive": archive_check,
        "non_empty_matches_messages": summary_payload.get("non_empty_messages") == len(summary_payload.get("messages") or []),
        "latest_summary_input": str(latest_file("raw_*_summary_input.json")),
    }

    if not report["artifact_checks"]["non_empty_matches_messages"]:
        report["status"] = "validation_failed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report_path = write_collection_report(report)
        print(json.dumps({"status": report["status"], "report_path": str(report_path)}, ensure_ascii=False))
        return 1

    for artifact_name in ("raw_log", "summary_input", "archive"):
        if not report["artifact_checks"][artifact_name]["is_fresh"]:
            report["status"] = "stale_artifact"
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            report_path = write_collection_report(report)
            print(json.dumps({"status": report["status"], "report_path": str(report_path)}, ensure_ascii=False))
            return 1

    report["status"] = "ok"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report_path = write_collection_report(report)
    print(json.dumps({
        "status": report["status"],
        "report_path": str(report_path),
        "summary_input": payload["summary_input"],
        "raw_log": payload["raw_log"],
        "non_empty_messages": payload["non_empty_messages"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
