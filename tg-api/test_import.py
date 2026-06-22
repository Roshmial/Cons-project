# Test import
import sys
sys.path.insert(0, '/home/hermes/workspace/TG-API')

try:
    import app
    print("Import successful")
except Exception as e:
    print(f"Import failed: {e}")