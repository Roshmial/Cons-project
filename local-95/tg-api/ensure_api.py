import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8001
BASE_DIR = Path(__file__).resolve().parent


def port_open(host=HOST, port=PORT, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def load_tg_api_env() -> dict[str, str]:
    env = os.environ.copy()
    env_path = Path.home() / '.hermes' / 'tg-api.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            env.setdefault(key.strip(), value.strip())
    return env


def main():
    if port_open():
        print("api_status=already_running")
        return 0

    env = load_tg_api_env()

    log_path = BASE_DIR / "api_server.log"
    log_file = open(log_path, "a", encoding="utf-8")
    subprocess.Popen(
        ["/usr/bin/bash", str(BASE_DIR / "run_tg_api_service.sh")],
        cwd=str(BASE_DIR),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        close_fds=True,
    )

    deadline = time.time() + 20
    while time.time() < deadline:
        if port_open():
            print(f"api_status=started log={log_path}")
            return 0
        time.sleep(0.5)

    print(f"api_status=failed_to_start log={log_path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
