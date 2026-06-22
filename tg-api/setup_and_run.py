import os
import subprocess

# Setup venv for the whole process
def setup_env():
    print("Setting up virtual environment...")
    subprocess.run(["python3", "-m", "venv", "venv"], cwd="/home/hermes/workspace/TG-API", check=True)
    subprocess.run(["./venv/bin/pip", "install", "telethon", "pyyaml"], cwd="/home/hermes/workspace/TG-API", check=True)

def main():
    setup_env()
    print("Running orchestration...")
    # Use the venv python for the orchestrator too
    subprocess.run(["/home/hermes/workspace/TG-API/venv/bin/python3", "/home/hermes/workspace/TG-API/orchestrator.py"], check=True)

if __name__ == "__main__":
    main()
