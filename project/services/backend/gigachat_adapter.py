from __future__ import annotations

import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from flask import Flask, Response, jsonify, request


app = Flask(__name__)

DEFAULT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
DEFAULT_API_BASE_URL = "https://api.giga.chat/v1"
DEFAULT_SCOPE = "GIGACHAT_API_B2B"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_TOKEN_SKEW_SECONDS = 60

_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_calls>(.*?)</tool_calls>", re.DOTALL | re.IGNORECASE)
_INVOKE_RE = re.compile(r"<invoke\s+name=\"([^\"]+)\"\s*>(.*?)</invoke>", re.DOTALL | re.IGNORECASE)
_PARAMETER_RE = re.compile(r"<parameter\s+name=\"([^\"]+)\"\s*>(.*?)</parameter>", re.DOTALL | re.IGNORECASE)


class AdapterError(RuntimeError):
    def __init__(self, code: str, status_code: int = 500, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.detail = detail or code


@dataclass
class TokenState:
    access_token: str
    expires_at: float


class GigaChatTokenManager:
    def __init__(
        self,
        *,
        oauth_url: str,
        credentials: str,
        scope: str,
        timeout_seconds: int,
        verify_ssl: bool,
        token_skew_seconds: int = DEFAULT_TOKEN_SKEW_SECONDS,
        ca_cert_file: str | None = None,
    ):
        self.oauth_url = oauth_url.rstrip("/")
        self.credentials = credentials
        self.scope = scope
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl
        self.token_skew_seconds = token_skew_seconds
        self.ca_cert_file = safe_text(ca_cert_file).strip() or None
        self._lock = threading.Lock()
        self._state: TokenState | None = None

    def get_token(self) -> str:
        now = time.time()
        with self._lock:
            if self._state and now < (self._state.expires_at - self.token_skew_seconds):
                return self._state.access_token
            token, expires_at = self._fetch_token()
            self._state = TokenState(access_token=token, expires_at=expires_at)
            return token

    def _fetch_token(self) -> tuple[str, float]:
        body = urllib.parse.urlencode({"scope": self.scope}).encode("utf-8")
        req = urllib.request.Request(
            self.oauth_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {self.credentials}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=build_ssl_context(self.verify_ssl, self.ca_cert_file)) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AdapterError("gigachat_oauth_http_error", 502, f"{exc.code}: {detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise AdapterError("gigachat_oauth_unreachable", 502, str(exc.reason)) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AdapterError("gigachat_oauth_timeout", 504, str(exc)) from exc

        access_token = safe_text(payload.get("access_token") or payload.get("token"))
        if not access_token:
            raise AdapterError("gigachat_oauth_missing_token", 502, json.dumps(payload, ensure_ascii=False)[:400])
        expires_at = parse_expiry(payload)
        return access_token, expires_at


_TOKEN_MANAGER: GigaChatTokenManager | None = None


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def env_flag(name: str, default: bool) -> bool:
    raw = safe_text(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def build_ssl_context(verify_ssl: bool, ca_cert_file: str | None = None) -> ssl.SSLContext | None:
    if not verify_ssl:
        return ssl._create_unverified_context()
    if ca_cert_file:
        return ssl.create_default_context(cafile=ca_cert_file)
    return None


def parse_expiry(payload: dict[str, Any]) -> float:
    raw = payload.get("expires_at") or payload.get("expiresAt") or payload.get("exp")
    now = time.time()
    if raw is None:
        return now + 1800
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 10_000_000_000:
            return value / 1000.0
        if value > now + 60:
            return value
    text = safe_text(raw).strip()
    if text.isdigit():
        value = float(text)
        if value > 10_000_000_000:
            return value / 1000.0
        if value > now + 60:
            return value
    return now + 1800


def adapter_settings() -> dict[str, Any]:
    return {
        "oauth_url": safe_text(os.getenv("GIGACHAT_ADAPTER_OAUTH_URL", DEFAULT_OAUTH_URL)).rstrip("/"),
        "api_base_url": safe_text(os.getenv("GIGACHAT_ADAPTER_API_BASE_URL", DEFAULT_API_BASE_URL)).rstrip("/"),
        "credentials": safe_text(os.getenv("GIGACHAT_ADAPTER_CREDENTIALS", "")),
        "scope": safe_text(os.getenv("GIGACHAT_ADAPTER_SCOPE", DEFAULT_SCOPE)) or DEFAULT_SCOPE,
        "timeout_seconds": int(safe_text(os.getenv("GIGACHAT_ADAPTER_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))) or DEFAULT_TIMEOUT_SECONDS),
        "verify_ssl": env_flag("GIGACHAT_ADAPTER_VERIFY_SSL", True),
        "token_skew_seconds": int(safe_text(os.getenv("GIGACHAT_ADAPTER_TOKEN_SKEW_SECONDS", str(DEFAULT_TOKEN_SKEW_SECONDS))) or DEFAULT_TOKEN_SKEW_SECONDS),
        "ca_cert_file": safe_text(os.getenv("GIGACHAT_ADAPTER_CA_CERT_FILE", "")).strip(),
    }


def get_token_manager() -> GigaChatTokenManager:
    global _TOKEN_MANAGER
    settings = adapter_settings()
    if not settings["credentials"]:
        raise AdapterError("gigachat_credentials_missing", 500, "Set GIGACHAT_ADAPTER_CREDENTIALS")
    token_settings = {
        "oauth_url": settings["oauth_url"],
        "credentials": settings["credentials"],
        "scope": settings["scope"],
        "timeout_seconds": settings["timeout_seconds"],
        "verify_ssl": settings["verify_ssl"],
        "token_skew_seconds": settings["token_skew_seconds"],
        "ca_cert_file": settings["ca_cert_file"] or None,
    }
    if _TOKEN_MANAGER is None:
        _TOKEN_MANAGER = GigaChatTokenManager(**token_settings)
    else:
        if (
            _TOKEN_MANAGER.oauth_url != token_settings["oauth_url"]
            or _TOKEN_MANAGER.credentials != token_settings["credentials"]
            or _TOKEN_MANAGER.scope != token_settings["scope"]
            or _TOKEN_MANAGER.timeout_seconds != token_settings["timeout_seconds"]
            or _TOKEN_MANAGER.verify_ssl != token_settings["verify_ssl"]
            or _TOKEN_MANAGER.token_skew_seconds != token_settings["token_skew_seconds"]
            or _TOKEN_MANAGER.ca_cert_file != token_settings["ca_cert_file"]
        ):
            _TOKEN_MANAGER = GigaChatTokenManager(**token_settings)
    return _TOKEN_MANAGER


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _normalize_message_content(value: Any) -> Any:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value


def _parse_arguments_string(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = safe_text(value).strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _tool_choice_to_function_call(tool_choice: Any) -> Any:
    if tool_choice in (None, ""):
        return None
    if tool_choice in {"auto", "none"}:
        return tool_choice
    if tool_choice == "required":
        return "auto"
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            function = tool_choice.get("function") or {}
            name = safe_text(function.get("name")).strip()
            if name:
                return {"name": name}
        name = safe_text(tool_choice.get("name")).strip()
        if name:
            return {"name": name}
    return None


def _merge_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return []
    if len(messages) == 1:
        return messages
    merged = _json_clone(messages[0])
    content_parts = [safe_text(item.get("content")).strip() for item in messages]
    merged["content"] = "\n\n".join(part for part in content_parts if part)
    return [merged]


def normalize_openai_request(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _json_clone(payload)
    messages = normalized.get("messages")
    if not isinstance(messages, list):
        return normalized

    functions = []
    for tool in normalized.pop("tools", []) or []:
        if isinstance(tool, dict) and tool.get("type") == "function":
            function_def = tool.get("function")
            if isinstance(function_def, dict):
                functions.append(_json_clone(function_def))
    if functions:
        normalized["functions"] = functions

    function_call = _tool_choice_to_function_call(normalized.pop("tool_choice", None))
    if function_call is not None:
        normalized["function_call"] = function_call

    normalized.pop("parallel_tool_calls", None)

    tool_name_by_id: dict[str, str] = {}
    normalized_messages: list[dict[str, Any]] = []
    deferred_system_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = safe_text(message.get("role")).strip()
        if role == "assistant" and isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
            tool_call = message["tool_calls"][0]
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            name = safe_text(function.get("name")).strip()
            tool_call_id = safe_text(tool_call.get("id")).strip()
            if name and tool_call_id:
                tool_name_by_id[tool_call_id] = name
            normalized_message = {
                "role": "assistant",
                "function_call": {
                    "name": name,
                    "arguments": _parse_arguments_string(function.get("arguments")),
                },
            }
            functions_state_id = safe_text(message.get("functions_state_id")).strip()
            if functions_state_id:
                normalized_message["functions_state_id"] = functions_state_id
            content = message.get("content")
            if content not in (None, ""):
                normalized_message["content"] = _normalize_message_content(content)
            normalized_messages.append(normalized_message)
            continue
        if role == "tool":
            tool_call_id = safe_text(message.get("tool_call_id")).strip()
            function_name = safe_text(message.get("name")).strip() or tool_name_by_id.get(tool_call_id, "")
            if not function_name:
                raise AdapterError("tool_message_function_name_missing", 400, "Cannot map tool message to GigaChat function result")
            normalized_messages.append(
                {
                    "role": "function",
                    "name": function_name,
                    "content": _normalize_message_content(message.get("content")),
                }
            )
            continue
        normalized_message = _json_clone(message)
        if "content" in normalized_message:
            normalized_message["content"] = _normalize_message_content(normalized_message.get("content"))
        if role == "system":
            deferred_system_messages.append(normalized_message)
        else:
            normalized_messages.append(normalized_message)
    normalized["messages"] = [*_merge_system_messages(deferred_system_messages), *normalized_messages]
    return normalized


def _extract_xml_tool_calls(content: str) -> list[dict[str, Any]]:
    block_match = _TOOL_CALL_BLOCK_RE.search(content)
    if not block_match:
        return []
    block = block_match.group(1)
    tool_calls = []
    for invoke_match in _INVOKE_RE.finditer(block):
        name = invoke_match.group(1).strip()
        invoke_body = invoke_match.group(2)
        arguments: dict[str, Any] = {}
        for parameter_match in _PARAMETER_RE.finditer(invoke_body):
            param_name = parameter_match.group(1).strip()
            param_value = parameter_match.group(2).strip()
            arguments[param_name] = param_value
        tool_calls.append(
            {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )
    return tool_calls


def normalize_gigachat_response(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _json_clone(payload)
    choices = normalized.get("choices")
    if not isinstance(choices, list):
        return normalized

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue

        function_call = message.pop("function_call", None)
        if isinstance(function_call, dict):
            name = safe_text(function_call.get("name")).strip()
            arguments = function_call.get("arguments", {})
            message["tool_calls"] = [
                {
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, (dict, list)) else safe_text(arguments),
                    },
                }
            ]
            if choice.get("finish_reason") == "function_call":
                choice["finish_reason"] = "tool_calls"
            message.setdefault("content", None)
            continue

        content = message.get("content")
        if isinstance(content, str):
            tool_calls = _extract_xml_tool_calls(content)
            if tool_calls:
                message["tool_calls"] = tool_calls
                choice["finish_reason"] = "tool_calls"
                message["content"] = None

    return normalized


def proxy_chat_completions(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    settings = adapter_settings()
    token = get_token_manager().get_token()
    normalized_request = normalize_openai_request(payload)
    body = json.dumps(normalized_request, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{settings['api_base_url']}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=settings["timeout_seconds"], context=build_ssl_context(settings["verify_ssl"], settings["ca_cert_file"] or None)) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw)
            return normalize_gigachat_response(payload), getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AdapterError("gigachat_chat_http_error", 502, f"{exc.code}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise AdapterError("gigachat_chat_unreachable", 502, str(exc.reason)) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise AdapterError("gigachat_chat_timeout", 504, str(exc)) from exc


@app.get("/healthz")
def healthz() -> Response:
    settings = adapter_settings()
    payload = {
        "ok": True,
        "provider": "gigachat",
        "api_base_url": settings["api_base_url"],
        "oauth_url": settings["oauth_url"],
        "credentials_configured": bool(settings["credentials"]),
        "ca_cert_file": settings["ca_cert_file"] or None,
    }
    return jsonify(payload)


@app.post("/v1/chat/completions")
def chat_completions() -> Response:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise AdapterError("invalid_json_payload", 400, "JSON body is required")
    if not isinstance(payload.get("messages"), list) or not payload.get("messages"):
        raise AdapterError("messages_required", 400, "messages[] is required")
    proxied_payload, status_code = proxy_chat_completions(payload)
    return Response(json.dumps(proxied_payload, ensure_ascii=False), status=status_code, content_type="application/json; charset=utf-8")


@app.errorhandler(AdapterError)
def handle_adapter_error(exc: AdapterError) -> Response:
    return jsonify({"error_type": exc.code, "message": exc.detail}), exc.status_code


def reset_token_manager() -> None:
    global _TOKEN_MANAGER
    _TOKEN_MANAGER = None


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8795")))
