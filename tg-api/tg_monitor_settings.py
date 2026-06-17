import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _read_setting(name: str, default: str) -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value
    file_name = {
        "TG_MONITOR_CONFIG_NAME": ".tg-monitor-config-name",
        "TG_MONITOR_PROFILE_NAME": ".tg-monitor-profile-name",
    }[name]
    path = BASE_DIR / file_name
    if path.exists():
        file_value = path.read_text(encoding="utf-8").strip()
        if file_value:
            return file_value
    return default


DEFAULT_CONFIG_NAME = _read_setting("TG_MONITOR_CONFIG_NAME", "daily")
DEFAULT_PROFILE_NAME = _read_setting("TG_MONITOR_PROFILE_NAME", "profile_1")
