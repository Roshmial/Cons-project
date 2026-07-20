from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import unittest
import urllib.error
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


class GigaChatAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["GIGACHAT_ADAPTER_CREDENTIALS"] = "test-basic-credentials"
        module_path = Path(__file__).resolve().parent / "gigachat_adapter.py"
        if str(module_path.parent) not in sys.path:
            sys.path.insert(0, str(module_path.parent))
        spec = importlib.util.spec_from_file_location("gigachat_adapter_test_module", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.adapter = module
        cls.client = module.app.test_client()

    def setUp(self):
        self.adapter.reset_token_manager()

    def test_token_manager_fetches_and_caches_token(self):
        calls = []

        def fake_urlopen(req, timeout=0, context=None):
            calls.append(req.full_url)
            return FakeHTTPResponse({"access_token": "token-1", "expires_at": 4102444800000})

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            manager = self.adapter.get_token_manager()
            token_a = manager.get_token()
            token_b = manager.get_token()

        self.assertEqual(token_a, "token-1")
        self.assertEqual(token_b, "token-1")
        self.assertEqual(calls.count(self.adapter.adapter_settings()["oauth_url"]), 1)

    def test_token_request_uses_basic_auth_and_rquid(self):
        captured = {}

        def fake_urlopen(req, timeout=0, context=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = req.data.decode("utf-8")
            return FakeHTTPResponse({"access_token": "token-2", "expires_at": 4102444800000})

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            manager = self.adapter.get_token_manager()
            manager.get_token()

        headers = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(captured["url"], self.adapter.adapter_settings()["oauth_url"])
        self.assertEqual(headers["authorization"], "Basic test-basic-credentials")
        self.assertEqual(headers["content-type"], "application/x-www-form-urlencoded")
        self.assertIn("rquid", headers)
        self.assertEqual(captured["body"], "scope=GIGACHAT_API_B2B")

    def test_chat_completions_proxies_openai_shape_to_gigachat(self):
        oauth_url = self.adapter.adapter_settings()["oauth_url"]
        chat_url = f"{self.adapter.adapter_settings()['api_base_url']}/chat/completions"
        captured = {"chat_headers": None, "chat_body": None}

        def fake_urlopen(req, timeout=0, context=None):
            if req.full_url == oauth_url:
                return FakeHTTPResponse({"access_token": "token-3", "expires_at": 4102444800000})
            if req.full_url == chat_url:
                captured["chat_headers"] = dict(req.header_items())
                captured["chat_body"] = json.loads(req.data.decode("utf-8"))
                return FakeHTTPResponse({
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    "model": "GigaChat-3-Ultra",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                })
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/v1/chat/completions",
                json={"model": "GigaChat-3-Ultra", "stream": False, "messages": [{"role": "user", "content": "Привет"}]},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["choices"][0]["message"]["content"], "ok")
        headers = {k.lower(): v for k, v in captured["chat_headers"].items()}
        self.assertEqual(headers["authorization"], "Bearer token-3")
        self.assertEqual(captured["chat_body"]["messages"][0]["content"], "Привет")
        self.assertEqual(captured["chat_body"]["model"], "GigaChat-3-Ultra")

    def test_tools_request_maps_to_functions_and_response_tool_calls(self):
        oauth_url = self.adapter.adapter_settings()["oauth_url"]
        chat_url = f"{self.adapter.adapter_settings()['api_base_url']}/chat/completions"
        captured = {"chat_body": None}

        def fake_urlopen(req, timeout=0, context=None):
            if req.full_url == oauth_url:
                return FakeHTTPResponse({"access_token": "token-4", "expires_at": 4102444800000})
            if req.full_url == chat_url:
                captured["chat_body"] = json.loads(req.data.decode("utf-8"))
                return FakeHTTPResponse({
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "function_call": {
                                "name": "get_time",
                                "arguments": {"timezone": "UTC"},
                            },
                        },
                        "finish_reason": "function_call",
                        "index": 0,
                    }],
                    "model": "GigaChat-3-Ultra",
                })
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "GigaChat-3-Ultra",
                    "messages": [
                        {"role": "user", "content": "Скажи текущее время"},
                        {"role": "system", "content": "Отвечай кратко"},
                    ],
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "get_time",
                            "description": "Возвращает время",
                            "parameters": {
                                "type": "object",
                                "properties": {"timezone": {"type": "string"}},
                            },
                        },
                    }],
                    "tool_choice": "auto",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["chat_body"]["function_call"], "auto")
        self.assertEqual(captured["chat_body"]["functions"][0]["name"], "get_time")
        self.assertEqual(captured["chat_body"]["messages"][0]["role"], "system")
        self.assertEqual(captured["chat_body"]["messages"][0]["content"], "Отвечай кратко")
        self.assertEqual(captured["chat_body"]["messages"][1]["role"], "user")
        payload = response.get_json()
        tool_calls = payload["choices"][0]["message"]["tool_calls"]
        self.assertEqual(payload["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(tool_calls[0]["function"]["name"], "get_time")
        self.assertEqual(json.loads(tool_calls[0]["function"]["arguments"]), {"timezone": "UTC"})

    def test_multiple_system_messages_are_merged_and_moved_to_front(self):
        oauth_url = self.adapter.adapter_settings()["oauth_url"]
        chat_url = f"{self.adapter.adapter_settings()['api_base_url']}/chat/completions"
        captured = {"chat_body": None}

        def fake_urlopen(req, timeout=0, context=None):
            if req.full_url == oauth_url:
                return FakeHTTPResponse({"access_token": "token-4b", "expires_at": 4102444800000})
            if req.full_url == chat_url:
                captured["chat_body"] = json.loads(req.data.decode("utf-8"))
                return FakeHTTPResponse({
                    "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop", "index": 0}],
                    "model": "GigaChat-3-Ultra",
                })
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "GigaChat-3-Ultra",
                    "messages": [
                        {"role": "user", "content": "Скажи текущее время"},
                        {"role": "system", "content": "Инструкция 1"},
                        {"role": "assistant", "content": "Промежуточный ответ"},
                        {"role": "system", "content": "Инструкция 2"},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["chat_body"]["messages"][0]["role"], "system")
        self.assertEqual(captured["chat_body"]["messages"][0]["content"], "Инструкция 1\n\nИнструкция 2")
        self.assertEqual(captured["chat_body"]["messages"][1]["role"], "user")
        self.assertEqual(captured["chat_body"]["messages"][2]["role"], "assistant")

    def test_tool_messages_map_back_to_function_role(self):
        oauth_url = self.adapter.adapter_settings()["oauth_url"]
        chat_url = f"{self.adapter.adapter_settings()['api_base_url']}/chat/completions"
        captured = {"chat_body": None}

        def fake_urlopen(req, timeout=0, context=None):
            if req.full_url == oauth_url:
                return FakeHTTPResponse({"access_token": "token-5", "expires_at": 4102444800000})
            if req.full_url == chat_url:
                captured["chat_body"] = json.loads(req.data.decode("utf-8"))
                return FakeHTTPResponse({
                    "choices": [{"message": {"role": "assistant", "content": "Готово"}, "index": 0, "finish_reason": "stop"}],
                    "model": "GigaChat-3-Ultra",
                })
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "GigaChat-3-Ultra",
                    "messages": [
                        {"role": "user", "content": "Скажи время"},
                        {
                            "role": "assistant",
                            "functions_state_id": "state-123",
                            "tool_calls": [{
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "get_time", "arguments": "{\"timezone\":\"UTC\"}"},
                            }],
                        },
                        {"role": "tool", "tool_call_id": "call_123", "content": "2026-07-17T06:50:00Z"},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        messages = captured["chat_body"]["messages"]
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["function_call"]["name"], "get_time")
        self.assertEqual(messages[1]["functions_state_id"], "state-123")
        self.assertEqual(messages[2], {"role": "function", "name": "get_time", "content": "2026-07-17T06:50:00Z"})

    def test_xml_tool_calls_are_normalized(self):
        oauth_url = self.adapter.adapter_settings()["oauth_url"]
        chat_url = f"{self.adapter.adapter_settings()['api_base_url']}/chat/completions"

        def fake_urlopen(req, timeout=0, context=None):
            if req.full_url == oauth_url:
                return FakeHTTPResponse({"access_token": "token-6", "expires_at": 4102444800000})
            if req.full_url == chat_url:
                return FakeHTTPResponse({
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "<tool_calls>\n<invoke name=\"get_time\">\n<parameter name=\"timezone\">UTC</parameter>\n</invoke>\n</tool_calls>",
                        },
                        "finish_reason": "stop",
                        "index": 0,
                    }],
                    "model": "GigaChat-3-Ultra",
                })
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/v1/chat/completions",
                json={"model": "GigaChat-3-Ultra", "messages": [{"role": "user", "content": "Скажи время"}]},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        tool_calls = payload["choices"][0]["message"]["tool_calls"]
        self.assertEqual(payload["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(tool_calls[0]["function"]["name"], "get_time")
        self.assertEqual(json.loads(tool_calls[0]["function"]["arguments"]), {"timezone": "UTC"})
        self.assertIsNone(payload["choices"][0]["message"]["content"])

    def test_chat_completions_requires_messages(self):
        response = self.client.post("/v1/chat/completions", json={"model": "GigaChat-3-Ultra"})
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error_type"], "messages_required")

    def test_chat_completions_surfaces_upstream_http_error(self):
        oauth_url = self.adapter.adapter_settings()["oauth_url"]
        chat_url = f"{self.adapter.adapter_settings()['api_base_url']}/chat/completions"

        def fake_urlopen(req, timeout=0, context=None):
            if req.full_url == oauth_url:
                return FakeHTTPResponse({"access_token": "token-7", "expires_at": 4102444800000})
            if req.full_url == chat_url:
                raise urllib.error.HTTPError(
                    chat_url,
                    401,
                    "Unauthorized",
                    hdrs=None,
                    fp=io.BytesIO(b'{"message":"bad token"}'),
                )
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/v1/chat/completions",
                json={"model": "GigaChat-3-Ultra", "messages": [{"role": "user", "content": "Привет"}]},
            )

        self.assertEqual(response.status_code, 502)
        payload = response.get_json()
        self.assertEqual(payload["error_type"], "gigachat_chat_http_error")
        self.assertIn("401", payload["message"])

    def test_chat_completions_surfaces_upstream_timeout_as_json(self):
        oauth_url = self.adapter.adapter_settings()["oauth_url"]
        chat_url = f"{self.adapter.adapter_settings()['api_base_url']}/chat/completions"

        def fake_urlopen(req, timeout=0, context=None):
            if req.full_url == oauth_url:
                return FakeHTTPResponse({"access_token": "token-8", "expires_at": 4102444800000})
            if req.full_url == chat_url:
                raise TimeoutError("The read operation timed out")
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with patch.object(self.adapter.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/v1/chat/completions",
                json={"model": "GigaChat-3-Ultra", "messages": [{"role": "user", "content": "Привет"}]},
            )

        self.assertEqual(response.status_code, 504)
        payload = response.get_json()
        self.assertEqual(payload["error_type"], "gigachat_chat_timeout")


if __name__ == "__main__":
    unittest.main()
