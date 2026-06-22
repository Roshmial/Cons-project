import os
import subprocess

# Path to the app.py
app_path = "/home/hermes/workspace/TG-API/app.py"

# Start Flask server in the background
# Using nohup to keep it running and redirecting output to a log file
process = subprocess.Popen(
    ["python3", app_path],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=os.environ.copy(),
    text=True
)

print(f"Started Flask server (PID: {process.pid})")
# Wait a few seconds for the server to start
import time
time.sleep(5)

# Now run the robust export script
export_process = subprocess.Popen(
    ["python3", "/home/hermes/workspace/TG-API/robust_export.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# Wait for export to complete and print its output
stdout, stderr = export_process.communicate()
print("Export script output:\n", stdout)
if stderr:
    print("Export script error:\n", stderr)

# Terminate the Flask server
process.terminate()
print("Flask server terminated.")
