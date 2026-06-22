import os
import subprocess
import time
import json

# IMPORTANT: We must ensure API_ID and API_HASH are set.
env = os.environ.copy()

# 1. Start Flask server
app_path = "/home/hermes/workspace/TG-API/app.py"
print("Launching Flask server...")
process = subprocess.Popen(
    ["python3", app_path],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    text=True
)

# Give it time to boot
time.sleep(7)

# 2. Run the robust export script
print("Starting robust export...")
export_process = subprocess.Popen(
    ["python3", "/home/hermes/workspace/TG-API/robust_export.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    text=True
)

# Print export progress in real-time
while True:
    line = export_process.stdout.readline()
    if not line and export_process.poll() is not None:
        break
    if line:
        print(line.strip())

# 3. Terminate the Flask server
print("Terminating Flask server...")
process.terminate()

# 4. Run analysis script
print("Running trend analysis...")
analysis_process = subprocess.Popen(
    ["python3", "/home/hermes/workspace/TG-API/analyze_trends.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    text=True
)

analysis_stdout, analysis_stderr = analysis_process.communicate()
print("Analysis output:\n", analysis_stdout)
if analysis_stderr:
    print("Analysis error:\n", analysis_stderr)
