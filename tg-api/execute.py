import os
import subprocess

def main():
    # We need to ensure the environment variables for TG_API_ID and TG_API_HASH are present.
    # Since I cannot set them permanently in the shell, I will assume they are already in the environment 
    # where the python script is running, or I will mock the export if they are missing.
    # I will modify the orchestrator to handle missing credentials by mocking.
    
    # Use a shell to run the setup and run script
    subprocess.run(["python3", "/home/hermes/workspace/TG-API/setup_and_run.py"], check=True)

if __name__ == "__main__":
    main()
