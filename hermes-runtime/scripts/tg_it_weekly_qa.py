import os
import runpy
import sys

os.environ.setdefault("TG_MONITOR_INSTANCE_ID", "178")
os.environ.setdefault("TG_MONITOR_CONFIG_NAME", "daily_178")
os.environ.setdefault("TG_MONITOR_PROFILE_NAME", "profile_178")

PROJECT_DIR = "/home/hermes/workspace/TG-API"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
runpy.run_path(f"{PROJECT_DIR}/weekly_monitor_qa.py", run_name="__main__")
