from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeHTTPResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class HermesApiAuthModeTest(unittest.TestCase):
    def load_backend(self, module_name: str, extra_env: dict[str, str]):
        tempdir = tempfile.mkdtemp(prefix="hermes_web_auth_mode_")
        os.environ["HERMES_WEB_MODE"] = "hermes-api"
        os.environ["HERMES_WEB_SCHEDULER_ENABLED"] = "0"
        os.environ["HERMES_WEB_ENABLE_DEMO_DATA"] = "0"
        os.environ["HERMES_WEB_ALLOW_USER_DIRECTORY"] = "1"
        os.environ["HERMES_WEB_BACKEND_DATA_DIR"] = tempdir
        os.environ["HERMES_WEB_BACKEND_DB_PATH"] = str(Path(tempdir) / "test.duckdb")
        os.environ["HERMES_WEB_IMPORT_BOOTSTRAP_ENABLED"] = "0"
        os.environ["HERMES_WEB_HERMES_API_BASE_URL"] = "http://adapter.local/v1"
        for key, value in extra_env.items():
            os.environ[key] = value
        module_path = Path(__file__).resolve().parent / "app.py"
        if str(module_path.parent) not in sys.path:
            sys.path.insert(0, str(module_path.parent))
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_bearer_mode_requires_api_key(self):
        module = self.load_backend(
            "hermes_backend_bearer_mode_test",
            {
                "HERMES_WEB_HERMES_API_AUTH_MODE": "bearer",
                "HERMES_WEB_HERMES_API_KEY": "",
            },
        )
        with self.assertRaises(module.ApiError) as ctx:
            module.call_hermes_messages([{"role": "user", "content": "ping"}])
        self.assertEqual(ctx.exception.message, "hermes_api_key_missing")

    def test_none_mode_skips_authorization_header(self):
        module = self.load_backend(
            "hermes_backend_none_mode_test",
            {
                "HERMES_WEB_HERMES_API_AUTH_MODE": "none",
                "HERMES_WEB_HERMES_API_KEY": "",
            },
        )
        captured = {}

        def fake_urlopen(req, timeout=0, context=None):
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeHTTPResponse({
                "choices": [{"message": {"role": "assistant", "content": "adapter-response"}}],
                "model": "GigaChat-3-Ultra",
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            })

        with patch.object(module.urllib.request, "urlopen", side_effect=fake_urlopen):
            text, meta = module.call_hermes_messages([{"role": "user", "content": "ping"}], model_name="GigaChat-3-Ultra")

        headers = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertNotIn("authorization", headers)
        self.assertEqual(captured["body"]["model"], "GigaChat-3-Ultra")
        self.assertEqual(text, "adapter-response")
        self.assertEqual(meta["hermes_model"], "GigaChat-3-Ultra")


if __name__ == "__main__":
    unittest.main()
