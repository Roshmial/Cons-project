import argparse
import json
import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import yaml

from tg_instance_paths import (
    ARCHIVE_DIR,
    ARCHIVE_JSONL,
    BASE_DIR,
    LATEST_NON_EMPTY_PATH,
    LATEST_SUMMARY_POINTER,
    RAW_LOGS_DIR as LOGS_DIR,
    SINCE_PATH as DEFAULT_SINCE_PATH,
    ensure_runtime_dirs,
)

DEFAULT_CONFIG_NAME = "daily"
DEFAULT_CONFIG_PATH = BASE_DIR / f"channels_{DEFAULT_CONFIG_NAME}.yml"
FALLBACK_CONFIG_PATH = BASE_DIR / "channels.yml"
API_URL = "http://localhost:8001/export"


class DataCollector:
    """Надежный инкрементальный сбор новых сообщений через локальный Telegram API."""

    def __init__(
        self,
        config_name: str = DEFAULT_CONFIG_NAME,
        profile_name: str = "profile_1",
        since_path: Path = DEFAULT_SINCE_PATH,
    ):
        self.config_name = config_name
        self.profile_name = profile_name
        self.config_path = self._resolve_config_path(config_name)
        self.since_path = Path(since_path)
        self.config = self._load_yaml(self.config_path)
        self.since_data = self._load_json(self.since_path)
        ensure_runtime_dirs()

    def _resolve_config_path(self, config_name: str) -> Path:
        candidates = [
            BASE_DIR / f"channels_{config_name}.yml",
            BASE_DIR / "channels.yml",
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(f"Конфиг не найден. Проверены: {candidates}")

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as file_obj:
            return yaml.safe_load(file_obj) or {}

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as file_obj:
                    return json.load(file_obj)
            except Exception as exc:
                print(f"Ошибка загрузки {path}: {exc}")
                return {}
        return {}

    def _save_since(self, data: Dict[str, int]) -> None:
        self.since_path.parent.mkdir(parents=True, exist_ok=True)
        with self.since_path.open("w", encoding="utf-8") as file_obj:
            json.dump(data, file_obj, indent=2, ensure_ascii=False)

    def _save_raw_log(self, data: Dict[str, Any]) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = LOGS_DIR / f"raw_{timestamp}.json"
        log_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return log_file

    def _message_text(self, msg: Dict[str, Any]) -> str:
        for key in ("text", "message", "raw_text"):
            value = msg.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _original_url(self, msg: Dict[str, Any]) -> Optional[str]:
        if msg.get("original_url"):
            return msg["original_url"]
        chat = msg.get("chat")
        msg_id = msg.get("id")
        if chat and msg_id:
            return f"https://t.me/{chat}/{msg_id}"
        return None

    def _extract_links(self, msg: Dict[str, Any], text: str) -> list[str]:
        links = []
        for link in msg.get("external_links") or []:
            if isinstance(link, str):
                links.append(link.strip())
        for link in re.findall(r"https?://[^\s)\]>\"'«»]+", text or ""):
            links.append(link.strip())

        result = []
        seen = set()
        for link in links:
            clean = link.rstrip(".,;:!?)]}")
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    def _enrich_message(self, msg: Dict[str, Any], collection_ts: str) -> Dict[str, Any]:
        text = self._message_text(msg)
        enriched = dict(msg)
        enriched["collection_ts"] = collection_ts
        enriched["original_url"] = self._original_url(msg)
        enriched["external_links"] = self._extract_links(msg, text)
        enriched["has_text"] = bool(text)
        return enriched

    def _append_archive_jsonl(self, messages: list[Dict[str, Any]], collection_ts: str) -> Path:
        with ARCHIVE_JSONL.open("a", encoding="utf-8") as file_obj:
            for msg in messages:
                file_obj.write(json.dumps(self._enrich_message(msg, collection_ts), ensure_ascii=False) + "\n")
        return ARCHIVE_JSONL

    def _summary_metadata(self, enriched: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "views",
            "forwards",
            "replies_count",
            "comments_enabled",
            "reactions",
            "edit_date",
            "grouped_id",
            "post_author",
            "media_type",
        )
        return {
            key: enriched.get(key)
            for key in keys
            if enriched.get(key) not in (None, [], "")
        }

    def _save_summary_input(self, raw_log_path: Path, messages: list[Dict[str, Any]], collection_ts: str) -> tuple[Path, Dict[str, Any]]:
        non_empty = []
        for msg in messages:
            text = self._message_text(msg)
            if not text:
                continue
            enriched = self._enrich_message(msg, collection_ts)
            non_empty.append(
                {
                    "chat": enriched.get("chat"),
                    "id": enriched.get("id"),
                    "date": enriched.get("date"),
                    "original_url": enriched.get("original_url"),
                    "external_links": enriched.get("external_links", []),
                    "metadata": self._summary_metadata(enriched),
                    "text": text,
                }
            )

        base_name = raw_log_path.stem
        summary_file = LOGS_DIR / f"{base_name}_summary_input.json"
        payload = {
            "raw_log": str(raw_log_path),
            "config_name": self.config_name,
            "profile_name": self.profile_name,
            "total_messages": len(messages),
            "non_empty_messages": len(non_empty),
            "empty_messages_skipped": len(messages) - len(non_empty),
            "messages": non_empty,
        }
        summary_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        LATEST_NON_EMPTY_PATH.write_text(json.dumps(non_empty, indent=2, ensure_ascii=False), encoding="utf-8")
        LATEST_SUMMARY_POINTER.write_text(str(summary_file), encoding="utf-8")
        return summary_file, payload

    def fetch_new_messages(self) -> Dict[str, Any]:
        profiles = self.config.get("profiles", {})
        profile = profiles.get(self.profile_name)
        if not profile:
            error_message = f"Профиль {self.profile_name} не найден в {self.config_path}"
            print(f"Ошибка: {error_message}")
            return {"status": "api_error", "error": error_message}

        request_since = {}
        for channel in profile.get("channels", []):
            username = channel.get("username")
            if username in self.since_data:
                request_since[username] = self.since_data[username]

        encoded_since = urllib.parse.quote(json.dumps(request_since, ensure_ascii=False))
        url = (
            f"{API_URL}?profile={self.profile_name}&config={self.config_name}&since={encoded_since}"
        )
        print(f"Запрос к API: {url}")

        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                error_message = str(data["error"])
                print(f"Ошибка API: {error_message}")
                return {"status": "api_error", "error": error_message, "response": data}
            return {"status": "ok", "data": data}
        except Exception as exc:
            error_message = str(exc)
            print(f"Ошибка при запросе: {error_message}")
            return {"status": "api_error", "error": error_message}

    def update_state(self, messages: list[Dict[str, Any]]) -> bool:
        updated = False
        for msg in messages:
            username = msg.get("chat")
            msg_id = msg.get("id")
            if username and msg_id:
                if username not in self.since_data or msg_id > self.since_data[username]:
                    self.since_data[username] = msg_id
                    updated = True
        if updated:
            self._save_since(self.since_data)
            print("Состояние (since.json) успешно обновлено.")
        else:
            print("Новых ID не обнаружено. Состояние не менялось.")
        return updated

    def collect(self) -> Dict[str, Any]:
        collection_ts = datetime.now().isoformat(timespec="seconds")
        print(f"=== Сбор данных [{collection_ts}] ===")
        api_result = self.fetch_new_messages()
        if api_result.get("status") == "api_error":
            return {
                "status": "api_error",
                "config_name": self.config_name,
                "profile_name": self.profile_name,
                "collection_ts": collection_ts,
                "error": api_result.get("error"),
            }

        data = api_result.get("data") or {}
        if not data.get("messages"):
            print("Новых сообщений нет.")
            return {
                "status": "no_new_messages",
                "config_name": self.config_name,
                "profile_name": self.profile_name,
                "collection_ts": collection_ts,
                "total_messages": 0,
                "non_empty_messages": 0,
                "empty_messages_skipped": 0,
            }

        messages = data["messages"]
        print(f"Найдено новых сообщений: {len(messages)}")

        log_path = self._save_raw_log(data)
        print(f"Сырые данные сохранены в: {log_path}")

        summary_path, summary_payload = self._save_summary_input(log_path, messages, collection_ts)
        print(f"Файл для сводки сохранен в: {summary_path}")
        print(
            "Для сводки: "
            f"{summary_payload['non_empty_messages']} непустых, "
            f"{summary_payload['empty_messages_skipped']} пустых сообщений пропущено."
        )

        archive_path = self._append_archive_jsonl(messages, collection_ts)
        print(f"Архив JSONL дополнен: {archive_path}")

        state_updated = self.update_state(messages)

        print("=== Сбор завершен ===\n")
        return {
            "status": "ok",
            "config_name": self.config_name,
            "profile_name": self.profile_name,
            "collection_ts": collection_ts,
            "raw_log": str(log_path),
            "summary_input": str(summary_path),
            "archive": str(archive_path),
            "total_messages": len(messages),
            "non_empty_messages": summary_payload["non_empty_messages"],
            "empty_messages_skipped": summary_payload["empty_messages_skipped"],
            "since_updated": state_updated,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME, help="Имя config без channels_.")
    parser.add_argument("--profile", default="profile_1", help="Профиль из YAML-конфига.")
    parser.add_argument("--since-file", default=str(DEFAULT_SINCE_PATH), help="Путь к since.json.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    collector = DataCollector(
        config_name=args.config,
        profile_name=args.profile,
        since_path=Path(args.since_file),
    )
    result = collector.collect()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get("status") in {"ok", "no_new_messages"} else 1)
