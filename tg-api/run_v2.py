import subprocess

try:
    result = subprocess.run(['python3', '/home/hermes/workspace/TG-API/execute_extraction_v2.py'], capture_output=True, text=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
except Exception as e:
    print(f"An error occurred: {e}")
