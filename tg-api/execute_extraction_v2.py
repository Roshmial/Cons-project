import os
import subprocess

base_dir = '/home/hermes/workspace/TG-API'
script_path = os.path.join(base_dir, 'extract_posts.py')
input_file = os.path.join(base_dir, 'runtime/178/archive/telegram_messages.jsonl')
output_file = os.path.join(base_dir, 'tg_export_since_15_06.csv')

print(f"Checking script: {script_path}")
if not os.path.exists(script_path):
    print("Error: Script not found.")
else:
    print(f"Checking input: {input_file}")
    if not os.path.exists(input_file):
        print("Error: Input file not found.")
    else:
        print("Running extraction...")
        try:
            result = subprocess.run(['python3', script_path], capture_output=True, text=True)
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            
            if os.path.exists(output_file):
                print(f"Checking output: {output_file}")
                with open(output_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    print(f"Output file created. Number of lines (including header): {len(lines)}")
            else:
                print("Error: Output file was not created.")
        except Exception as e:
            print(f"An error occurred during execution: {e}")
