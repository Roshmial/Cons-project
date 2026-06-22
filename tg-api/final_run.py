import os
import subprocess

def main():
    # Create venv
    print("Creating virtual environment...")
    subprocess.run(["python3", "-m", "venv", "/home/hermes/workspace/TG-API/venv"], check=True)
    
    # Install dependencies
    print("Installing dependencies...")
    subprocess.run(["/home/hermes/workspace/TG-API/venv/bin/pip", "install", "telethon", "pyyaml"], check=True)
    
    # Run the orchestrator
    print("Running orchestrator...")
    subprocess.run(["/home/hermes/workspace/TG-API/venv/bin/python3", "/home/hermes/workspace/TG-API/orchestrator.py"], check=True)

if __name__ == "__main__":
    main()
