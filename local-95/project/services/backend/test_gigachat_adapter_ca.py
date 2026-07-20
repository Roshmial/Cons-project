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


class GigaChatAdapterCATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ca_file = tempfile.NamedTemporaryFile(prefix="gigachat_ca_", suffix=".crt", delete=False)
        cls.ca_file.write(b"dummy-ca")
        cls.ca_file.flush()
        cls.ca_file.close()
        os.environ["GIGACHAT_ADAPTER_CREDENTIALS"] = "test-basic-credentials"
        os.environ["GIGACHAT_ADAPTER_CA_CERT_FILE"] = cls.ca_file.name
        module_path = Path(__file__).resolve().parent / "gigachat_adapter.py"
        if str(module_path.parent) not in sys.path:
            sys.path.insert(0, str(module_path.parent))
        spec = importlib.util.spec_from_file_location("gigachat_adapter_ca_test_module", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.adapter = module
        cls.client = module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        try:
            Path(cls.ca_file.name).unlink(missing_ok=True)
        except Exception:
            pass

    def setUp(self):
        self.adapter.reset_token_manager()

    def test_health_reports_ca_file(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["ca_cert_file"], self.ca_file.name)

    def test_token_fetch_passes_ca_file_into_ssl_context(self):
        captured = {}

        def fake_context(verify_ssl: bool, ca_cert_file: str | None = None):
            captured["verify_ssl"] = verify_ssl
            captured["ca_cert_file"] = ca_cert_file
            return None

        def fake_urlopen(req, timeout=0, context=None):
            captured["context"] = context
            return FakeHTTPResponse({"access_token": "token-ca", "expires_at": 4102444800000})

        with patch.object(self.adapter, "build_ssl_context", side_effect=fake_context):
            with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
                token = self.adapter.get_token_manager().get_token()

        self.assertEqual(token, "token-ca")
        self.assertTrue(captured["verify_ssl"])
        self.assertEqual(captured["ca_cert_file"], self.ca_file.name)


if __name__ == "__main__":
    unittest.main()
