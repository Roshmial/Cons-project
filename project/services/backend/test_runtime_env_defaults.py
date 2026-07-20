from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class RuntimeEnvDefaultsTest(unittest.TestCase):
    def test_runtime_env_uses_b2b_gigachat_defaults(self):
        project_root = Path(__file__).resolve().parents[2]
        script_path = project_root / "scripts" / "runtime_env.sh"
        with tempfile.TemporaryDirectory(prefix="runtime_env_home_") as tmp_home:
            cmd = [
                "bash",
                "-lc",
                f"set -euo pipefail; source {script_path}; python3 - <<'PY'\n"
                "import os, json\n"
                "print(json.dumps({\n"
                "  'GIGACHAT_ADAPTER_API_BASE_URL': os.environ.get('GIGACHAT_ADAPTER_API_BASE_URL'),\n"
                "  'GIGACHAT_ADAPTER_SCOPE': os.environ.get('GIGACHAT_ADAPTER_SCOPE'),\n"
                "}))\n"
                "PY",
            ]
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                env={"HOME": tmp_home, "PATH": os.environ.get("PATH", "")},
            )
        payload = __import__("json").loads(result.stdout.strip())
        self.assertEqual(payload["GIGACHAT_ADAPTER_API_BASE_URL"], "https://api.giga.chat/v1")
        self.assertEqual(payload["GIGACHAT_ADAPTER_SCOPE"], "GIGACHAT_API_B2B")


if __name__ == "__main__":
    unittest.main()
