import subprocess

try:
    result = subprocess.run(['python3', '/home/hermes/workspace/TG-API/extract_posts.py'], capture_output=True, text=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
except Exception as e:
    print(f"An error occurred: {e}")
