from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash


class HermesWebBackendSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.mkdtemp(prefix="hermes_web_mvp_test_")
        os.environ["HERMES_WEB_MODE"] = "mock-hermes"
        os.environ["HERMES_WEB_SCHEDULER_ENABLED"] = "0"
        os.environ["HERMES_WEB_ENABLE_DEMO_DATA"] = "1"
        os.environ["HERMES_WEB_ALLOW_USER_DIRECTORY"] = "1"
        os.environ["HERMES_WEB_BACKEND_DATA_DIR"] = cls.tempdir
        os.environ["HERMES_WEB_BACKEND_DB_PATH"] = str(Path(cls.tempdir) / "test.duckdb")
        os.environ["HERMES_WEB_IMPORT_BOOTSTRAP_ENABLED"] = "0"
        module_path = Path(__file__).resolve().parent / "app.py"
        if str(module_path.parent) not in sys.path:
            sys.path.insert(0, str(module_path.parent))
        spec = importlib.util.spec_from_file_location("hermes_web_backend_test_app", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.init_db()
        module.recover_interrupted_chat_tasks()
        cls.backend = module
        cls.client = module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tempdir, ignore_errors=True)

    def login(self, email="misha@demo.local", password="demo123"):
        response = self.client.post("/api/auth/login", json={"email": email, "password": password})
        if response.status_code != 200 and email == "misha@demo.local" and password == "demo123":
            response = self.client.post("/api/auth/login", json={"email": email, "password": "12345678"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["token"]

    def auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def create_user(self, email: str, role: str = "user") -> int:
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO users (
                    email, password_hash, role, name, timezone, language, team, title,
                    goals, style, constraints_text, pinned_json, assistant_profile_json,
                    interaction_memory_json, memory_last_processed_message_id,
                    onboarding_completed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
                """,
                (
                    email,
                    generate_password_hash("demo123"),
                    role,
                    email.split("@")[0],
                    "Europe/Moscow",
                    "ru",
                    "QA",
                    "Reviewer",
                    "Проверка доступа",
                    "Коротко и по делу",
                    "Без лишних привилегий",
                    "[]",
                    '{"tone":"business","answer_depth":"short","interaction_mode":"answer_directly","about_user":""}',
                    "[]",
                    0,
                    1,
                    ts,
                    ts,
                ),
            )
            return cur.fetchone()[0]

    def create_thread_with_messages(self, user_id: int, title: str, messages: list[tuple[str, str, dict]]) -> tuple[int, list[int]]:
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                "INSERT INTO threads (user_id, title, preview, archived, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?) RETURNING id",
                (user_id, title, title[:140], ts, ts),
            )
            thread_id = int(cur.fetchone()[0])
            message_ids = []
            for role, content, meta in messages:
                cur = conn.execute(
                    "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, ?, ?, ?, ?) RETURNING id",
                    (thread_id, role, content, ts, json.dumps(meta, ensure_ascii=False)),
                )
                message_ids.append(int(cur.fetchone()[0]))
            return thread_id, message_ids

    def test_job_threads_freshness_uses_delivery_and_user_messages_not_technical_touches(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            user_id = int(user_row["id"])
            base = "2026-06-22T10:00:00+00:00"
            cur = conn.execute(
                "INSERT INTO threads (user_id, title, preview, archived, thread_kind, job_id, created_at, updated_at) VALUES (?, ?, ?, 0, 'job', ?, ?, ?) RETURNING id",
                (user_id, "Job A", "A", 1001, base, "2026-06-22T12:30:00+00:00"),
            )
            job_a = int(cur.fetchone()[0])
            cur = conn.execute(
                "INSERT INTO threads (user_id, title, preview, archived, thread_kind, job_id, created_at, updated_at) VALUES (?, ?, ?, 0, 'job', ?, ?, ?) RETURNING id",
                (user_id, "Job B", "B", 1002, base, "2026-06-22T11:00:00+00:00"),
            )
            job_b = int(cur.fetchone()[0])
            conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', ?, ?, ?)",
                (job_a, "delivery old", "2026-06-22T10:05:00+00:00", json.dumps({"source": "job_run", "job_id": 1001, "message_kind": "job_delivery"}, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', ?, ?, ?)",
                (job_b, "delivery", "2026-06-22T10:10:00+00:00", json.dumps({"source": "job_run", "job_id": 1002, "message_kind": "job_delivery"}, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'user', ?, ?, ?)",
                (job_b, "уточнение", "2026-06-22T12:00:00+00:00", json.dumps({}, ensure_ascii=False)),
            )

        response = self.client.get("/api/threads", headers=self.auth_headers(token))
        self.assertEqual(response.status_code, 200)
        threads = response.get_json()["threads"]
        job_threads = [thread for thread in threads if thread.get("id") in {job_a, job_b}]
        self.assertEqual([thread["id"] for thread in job_threads[:2]], [job_b, job_a])
        freshness_map = {thread["id"]: thread.get("freshness_at") for thread in job_threads}
        self.assertEqual(freshness_map[job_b], "2026-06-22T12:00:00+00:00")
        self.assertEqual(freshness_map[job_a], "2026-06-22T10:05:00+00:00")
        user_touch_map = {thread["id"]: thread.get("last_user_interaction_at") for thread in job_threads}
        self.assertEqual(user_touch_map[job_b], "2026-06-22T12:00:00+00:00")
        self.assertIsNone(user_touch_map[job_a])

    def test_job_threads_endpoint_handles_delivery_meta_patterns_without_500(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            user_id = int(user_row["id"])
            base = "2026-06-22T09:00:00+00:00"
            cur = conn.execute(
                "INSERT INTO threads (user_id, title, preview, archived, thread_kind, job_id, created_at, updated_at) VALUES (?, ?, ?, 0, 'job', ?, ?, ?) RETURNING id",
                (user_id, "Job Meta", "meta", 2001, base, base),
            )
            thread_id = int(cur.fetchone()[0])
            conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', ?, ?, ?)",
                (thread_id, "delivery", "2026-06-22T09:05:00+00:00", json.dumps({"source": "job_run", "job_id": 2001, "message_kind": "job_delivery"}, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', ?, ?, ?)",
                (thread_id, "status", "2026-06-22T09:06:00+00:00", json.dumps({"message_kind": "processing_status"}, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', ?, ?, ?)",
                (thread_id, "file", "2026-06-22T09:07:00+00:00", json.dumps({"message_kind": "file_response"}, ensure_ascii=False)),
            )

        response = self.client.get("/api/threads", headers=self.auth_headers(token))
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["threads"]
        target = next(thread for thread in payload if thread.get("id") == thread_id)
        self.assertEqual(target.get("freshness_at"), "2026-06-22T09:05:00+00:00")

    def test_json_loads_unwraps_nested_json_strings(self):
        nested = json.dumps(json.dumps({"attachments": [{"original_name": "report.pdf"}]}, ensure_ascii=False), ensure_ascii=False)
        payload = self.backend.json_loads(nested, {})
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("attachments")[0].get("original_name"), "report.pdf")

    def test_serialize_message_exposes_safe_display_text_without_internal_reasoning(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Digest leak",
            [
                (
                    "assistant",
                    "We have the payload data. Need to extract top_candidates and selection_reasons.\nLet's parse them.\n\n## Дайджест за день\n\n- Новость 1\n- Новость 2",
                    {"message_kind": "job_delivery", "source": "hermes_cron"},
                ),
            ],
        )
        with self.backend.db_connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_ids[0],)).fetchone()

        payload = self.backend.serialize_message(row)
        self.assertIn("We have the payload data", payload["content"])
        self.assertEqual(payload["display_text"], "## Дайджест за день\n\n- Новость 1\n- Новость 2")
        self.assertEqual(payload["meta"]["display_text"], "## Дайджест за день\n\n- Новость 1\n- Новость 2")

    def test_extract_hermes_output_for_delivery_strips_internal_reasoning_prelude(self):
        raw = """# Hermes Cron Output

## Response
We have the payload data. Need to extract top_candidates and selection_reasons.
Let's parse them.

## Дайджест за день

- Новость 1
- Новость 2
"""
        result = self.backend.extract_hermes_output_for_delivery(raw)
        self.assertEqual(result, "## Дайджест за день\n\n- Новость 1\n- Новость 2")

    def test_build_message_display_text_strips_russian_internal_reasoning_prelude(self):
        raw = """Хорошо, пользователь спрашивает, чем я могу помочь. Нужно дать чёткий и структурированный ответ.
Сначала вспомню ключевые пункты из роли и системного промпта.
Но в данном вопросе он просто спрашивает об общих возможностях.

Я могу помочь в нескольких направлениях:
- разобрать рабочую ситуацию;
- сравнить варианты;
- предложить следующий шаг.
"""
        result = self.backend.build_message_display_text(raw)
        self.assertEqual(result, "Я могу помочь в нескольких направлениях:\n- разобрать рабочую ситуацию;\n- сравнить варианты;\n- предложить следующий шаг.")

    def test_serialize_message_exposes_assistant_result_contract(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Assistant contract",
            [
                ("assistant", "Обычный ответ", {"message_kind": "chat_response"}),
                ("assistant", "Нужно уточнение", {"message_kind": "clarification_request"}),
                ("assistant", "Файл приложен", {"message_kind": "file_response", "attachments": [{"original_name": "report.xlsx", "storage_key": "files/report.xlsx"}]}),
                ("assistant", "Дашборд готов", {"message_kind": "dashboard_result", "dashboard": {"title": "Рынок", "sections": []}}),
                ("assistant", "План сбора данных готов", {"message_kind": "collection_contract", "collection_contract": {"source_kind": "web", "output_format": "csv", "subject": "LegalAI", "missing_fields": []}}),
                ("assistant", "Нужно уточнить формат сбора", {"message_kind": "collection_contract", "collection_contract": {"source_kind": "web", "output_format": "", "subject": "LegalAI", "missing_fields": ["формат результата"]}}),
                ("assistant", "Исследование готово", {"message_kind": "chat_response", "structured_result": {"summary": "Рынок подтверждён частично", "findings": ["Есть спрос"], "evidence": ["Источник A"], "caveats": ["Нужна допроверка"]}}),
                ("assistant", "Таблица готова", {"message_kind": "chat_response", "structured_result": {"summary": "Сводная таблица", "columns": ["Вендор", "Выручка"], "rows": [["A", "10"], ["B", "20"]]}}),
            ],
        )
        with self.backend.db_connect() as conn:
            placeholders = ", ".join(["?"] * len(message_ids))
            rows = conn.execute(f"SELECT * FROM messages WHERE id IN ({placeholders}) ORDER BY id", tuple(message_ids)).fetchall()

        payloads = [self.backend.serialize_message(row) for row in rows]
        self.assertEqual(payloads[0]["assistant_result_kind"], "chat_answer")
        self.assertEqual(payloads[0]["output_mode"], "chat")
        self.assertIn("save_as_job", payloads[0]["next_actions"])
        self.assertEqual(payloads[1]["assistant_result_kind"], "clarification_needed")
        self.assertEqual(payloads[1]["output_mode"], "clarification")
        self.assertEqual(payloads[1]["next_actions"], ["clarify_request"])
        self.assertEqual(payloads[2]["assistant_result_kind"], "file_result")
        self.assertEqual(payloads[2]["output_mode"], "file")
        self.assertIn("open_artifact", payloads[2]["next_actions"])
        self.assertEqual(payloads[2]["meta"]["attachments"][0]["file_surface"]["file_kind"], "input_file")
        self.assertEqual(payloads[2]["meta"]["attachments"][0]["file_surface"]["file_origin"], "user_upload")
        self.assertEqual(payloads[3]["assistant_result_kind"], "artifact_result")
        self.assertEqual(payloads[3]["output_mode"], "artifact")
        self.assertIn("save_as_job", payloads[3]["next_actions"])
        self.assertEqual(payloads[3]["surface"]["assistant_result_kind"], "artifact_result")
        self.assertEqual(payloads[4]["assistant_result_kind"], "structured_result")
        self.assertEqual(payloads[4]["output_mode"], "structured")
        self.assertIn("export_result", payloads[4]["next_actions"])
        self.assertEqual(payloads[5]["assistant_result_kind"], "clarification_needed")
        self.assertEqual(payloads[5]["output_mode"], "clarification")
        self.assertEqual(payloads[5]["next_actions"], ["clarify_request"])
        self.assertEqual(payloads[6]["assistant_result_kind"], "research_result")
        self.assertEqual(payloads[6]["output_mode"], "structured")
        self.assertIn("export_result", payloads[6]["next_actions"])
        self.assertEqual(payloads[7]["assistant_result_kind"], "table_result")
        self.assertEqual(payloads[7]["output_mode"], "structured")
        self.assertIn("save_as_job", payloads[7]["next_actions"])

    def test_process_chat_task_persists_used_files_contract(self):
        with self.backend.db_connect() as conn:
            thread_id = conn.execute(
                "INSERT INTO threads (user_id, title, preview, archived, version, created_at, updated_at) VALUES (1, 'Used files thread', '', FALSE, 1, now(), now()) RETURNING id"
            ).fetchone()[0]
            user_meta = {
                "user_text": "Используй приложенный файл и коротко суммируй его.",
                "attachments": [{
                    "id": 77,
                    "source_file_id": 77,
                    "original_name": "brief.docx",
                    "stored_name": "brief.docx",
                    "relative_path": "uploads/brief.docx",
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "size_bytes": 2048,
                    "text_extracted": True,
                    "preview_text": "Ключевой контекст проекта и ограничения.",
                    "reused": True,
                    "file_kind": "reused_file",
                    "file_origin": "profile_reuse",
                }],
            }
            user_message_id = conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'user', ?, now(), ?) RETURNING id",
                (thread_id, 'Используй файл', json.dumps(user_meta, ensure_ascii=False)),
            ).fetchone()[0]
            assistant_message_id = conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', 'Готовлю ответ…', now(), ?) RETURNING id",
                (thread_id, json.dumps(self.backend.build_pending_assistant_meta(1), ensure_ascii=False)),
            ).fetchone()[0]
            task_id = conn.execute(
                "INSERT INTO chat_tasks (thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error) VALUES (?, 1, ?, ?, 'pending', '{}', now(), NULL, NULL, '') RETURNING id",
                (thread_id, user_message_id, assistant_message_id),
            ).fetchone()[0]

        original_call = self.backend.call_hermes_api
        try:
            self.backend.call_hermes_api = lambda *args, **kwargs: ('Краткая выжимка по файлу готова.', {'message_kind': 'chat_response'})
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.call_hermes_api = original_call

        with self.backend.db_connect() as conn:
            row = conn.execute("SELECT meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
        meta = json.loads(row["meta_json"])
        self.assertEqual(meta["used_file_ids"], [77])
        self.assertEqual(meta["used_files"][0]["file_surface"]["file_kind"], "reused_file")
        self.assertEqual(meta["used_files"][0]["file_surface"]["file_origin"], "profile_reuse")
        self.assertTrue(meta["used_files"][0]["file_surface"]["used_in_response"])

    def test_normalize_attachment_payload_exposes_extraction_and_preview_summaries(self):
        payload = self.backend.normalize_attachment_payload({
            'original_name': 'table.xlsx',
            'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text_extracted': True,
            'extraction_note': 'XLSX прочитан частично: формулы и скрытые листы могли не попасть в текст.',
            'preview_text': '[Лист: Q1]\nmanager | amount\nAlice | 1200\nBob | 3400',
        })
        self.assertEqual(payload['file_surface']['extraction_status'], 'partial')
        self.assertIn('частично', payload['extraction_summary'])
        self.assertTrue(payload['preview_summary'].startswith('[Лист: Q1]'))
        self.assertEqual(payload['preview_lines'][:2], ['[Лист: Q1]', 'manager | amount'])

    def test_get_thread_exposes_thread_files_for_user_and_assistant_results(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            thread_id = conn.execute(
                "INSERT INTO threads (user_id, title, preview, archived, version, created_at, updated_at) VALUES (1, 'Files thread', '', FALSE, 1, now(), now()) RETURNING id"
            ).fetchone()[0]
            user_message_id = conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'user', 'Вот входной файл', now(), ?) RETURNING id",
                (thread_id, json.dumps({"attachments": []}, ensure_ascii=False)),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO user_files (user_id, thread_id, message_id, original_name, stored_name, relative_path, mime_type, size_bytes, text_extracted, extraction_note, preview_text, extracted_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())",
                (1, thread_id, user_message_id, 'input.txt', 'input.txt', 'uploads/input.txt', 'text/plain', 128, True, '', 'Первая строка', 'Первая строка'),
            )
            assistant_meta = {
                "attachments": [{
                    "original_name": "market-os-2025.docx",
                    "stored_name": "market-os-2025.docx",
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "size_bytes": 40960,
                    "download_url": f"/api/messages/999/attachments/0",
                    "file_kind": "generated_result",
                    "file_origin": "generated_result",
                }]
            }
            conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', 'Документ готов', now(), ?)",
                (thread_id, json.dumps(assistant_meta, ensure_ascii=False)),
            )
        response = self.client.get(f"/api/threads/{thread_id}", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        thread_files = payload['thread_files']
        names = [item.get('original_name') for item in thread_files]
        self.assertIn('input.txt', names)
        self.assertIn('market-os-2025.docx', names)
        generated = next(item for item in thread_files if item.get('original_name') == 'market-os-2025.docx')
        self.assertEqual(generated['thread_file_role'], 'assistant_result')
        uploaded = next(item for item in thread_files if item.get('original_name') == 'input.txt')
        self.assertEqual(uploaded['thread_file_role'], 'user_file')

    def test_normalize_external_dashboard_payload_skips_fake_visual_fallback_without_numeric_data(self):
        dashboard = self.backend.normalize_external_dashboard_payload(
            {
                "title": "Интернет-исследование",
                "summary_cards": [{"label": "Режим", "value": "global_only"}],
                "sections": [
                    {"kind": "text_list", "title": "Что удалось установить", "items": ["Есть только текстовый вывод"]},
                ],
                "sources": [{"label": "Wikipedia"}],
            },
            "Есть только текстовый вывод и оговорки.",
            {"label": "Интернет-исследование", "item_key": "web"},
            {"source_mode": "global_only"},
            "Собери дашборд по истории BI",
        )
        section_kinds = [section.get("kind") for section in dashboard.get("sections", [])]
        self.assertNotIn("bar_list", section_kinds)
        self.assertNotIn("pie_list", section_kinds)
        self.assertIn("text_list", section_kinds)

    def test_market_overview_normalization_uses_contentful_fallback_and_cards(self):
        dashboard = self.backend.normalize_external_dashboard_payload(
            {
                "title": "Интернет-исследование",
                "sections": [
                    {"kind": "text_list", "title": "Черновой вывод", "items": ["Geely усиливает позиции в России, но точных сопоставимых чисел в текущем наборе мало."]},
                ],
            },
            "Есть первичный рыночный вывод, но без достаточной числовой базы.",
            {"label": "web_research", "route": "web_research"},
            {"source_mode": "global_only"},
            "Собери dashboard по рынку Geely в России: игроки, рыночные сигналы и ограничения",
        )
        self.assertEqual(dashboard["intent"], "market_overview")
        section_kinds = [section["kind"] for section in dashboard.get("sections", [])]
        self.assertIn("bar_list", section_kinds)
        cards_blob = json.dumps(dashboard.get("summary_cards", []), ensure_ascii=False).lower()
        self.assertIn("рынок и игроки", cards_blob)
        self.assertNotIn("global_only", cards_blob)
        self.assertNotIn("минимальная визуализация", json.dumps(dashboard.get("sections", []), ensure_ascii=False).lower())

    def test_external_dashboard_normalization_uses_shared_semantic_core(self):
        dashboard = self.backend.normalize_external_dashboard_payload(
            {
                "title": "Интернет-исследование",
                "sections": [
                    {"kind": "text_list", "title": "Черновой вывод", "items": ["Есть обзор рынка поставщиков и ограничений, но не хватает прямых сопоставимых метрик."]},
                ],
            },
            "Есть первичный обзор рынка и ограничений.",
            {"label": "vendor web research", "route": "web_research"},
            {"source_mode": "global_only"},
            "Собери procurement dashboard по vendors, spend concentration и supplier landscape",
        )
        self.assertEqual(dashboard["business_function"], "procurement")
        self.assertIn("source shape: web_structured", dashboard["subtitle"])
        labels = {card.get("label"): card for card in dashboard.get("summary_cards", [])}
        self.assertIn("Функция", labels)
        self.assertIn("Форма источника", labels)
        self.assertEqual(labels["Функция"]["value"], "Закупки")
        self.assertEqual(labels["Форма источника"]["value"], "Web structured")

    def test_comparison_normalization_uses_criteria_instead_of_technical_stub(self):
        dashboard = self.backend.normalize_external_dashboard_payload(
            {
                "title": "Интернет-исследование",
                "sections": [
                    {"kind": "text_list", "title": "Черновой вывод", "items": ["Есть несколько различий между вариантами, но набор данных пока неполный."]},
                ],
                "sources": [{"label": "Example"}],
            },
            "Есть несколько различий между вариантами, но набор данных пока неполный.",
            {"label": "Интернет-исследование", "item_key": "web_research"},
            {"source_mode": "global_only"},
            "Сравни BI-платформы и построй дашборд",
        )
        sections_blob = json.dumps(dashboard.get("sections", []), ensure_ascii=False).lower()
        self.assertIn("критерии и различия", sections_blob)
        self.assertNotIn("минимальная визуализация", sections_blob)
        self.assertNotIn("техническая заглушка", sections_blob)

    def test_evidence_board_normalization_uses_evidence_first_fallback(self):
        dashboard = self.backend.normalize_external_dashboard_payload(
            {
                "title": "Интернет-исследование",
                "sections": [
                    {"kind": "text_list", "title": "Черновой вывод", "items": ["Есть несколько подтверждений, но покрытие темы пока неполное."]},
                ],
                "sources": [{"label": "Example"}],
            },
            "Есть несколько подтверждений, но покрытие темы пока неполное.",
            {"label": "Интернет-исследование", "item_key": "web_research"},
            {"source_mode": "global_only"},
            "Собери evidence board по теме LegalAI",
        )
        sections_blob = json.dumps(dashboard.get("sections", []), ensure_ascii=False).lower()
        self.assertIn("что подтверждено", sections_blob)
        self.assertIn("где не хватает данных", sections_blob)
        self.assertNotIn("минимальная визуализация", sections_blob)

    def test_business_dataset_dashboard_for_crm_attachment_uses_funnel_and_numeric_sections(self):
        uploads_dir = Path(self.tempdir) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        csv_path = uploads_dir / "crm_leads.csv"
        csv_path.write_text(
            "lead_id,stage,manager,channel,amount,created_at\n"
            "1,New,Alice,Ads,1000,2026-05-01\n"
            "2,Qualified,Alice,Organic,2500,2026-05-02\n"
            "3,Won,Bob,Ads,5000,2026-05-15\n"
            "4,Lost,Bob,Referral,800,2026-06-03\n",
            encoding="utf-8",
        )
        attachment = {"relative_path": "uploads/crm_leads.csv", "original_name": "crm_leads.csv"}
        loaded = self.backend.load_dashboard_dataset_from_attachment(attachment)
        self.assertIsNotNone(loaded)
        dataset, source_meta = loaded
        payload = self.backend.build_generic_dataset_dashboard_payload(dataset, source_meta, "Проанализируй лиды CRM за месяц и построй дашборд")
        self.assertEqual(payload["dashboard"]["kind"], "business_function_analytics")
        self.assertEqual(payload["dashboard"]["title"], "Дашборд бизнес-метрик: Продажи")
        self.assertEqual(payload["dashboard"]["summary_cards"][0]["value"], "Продажи")
        sections_blob = json.dumps(payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Воронка по этапам", sections_blob)
        self.assertIn("Профиль метрики", sections_blob)
        self.assertIn("Динамика по периодам", sections_blob)

    def test_load_dashboard_dataset_from_xlsx_attachment_without_external_dependencies(self):
        uploads_dir = Path(self.tempdir) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        xlsx_path = uploads_dir / "sales.xlsx"
        with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<?xml version='1.0' encoding='UTF-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'><Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/><Default Extension='xml' ContentType='application/xml'/><Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/><Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/><Override PartName='/xl/sharedStrings.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml'/></Types>")
            archive.writestr("_rels/.rels", "<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>")
            archive.writestr("xl/workbook.xml", "<?xml version='1.0' encoding='UTF-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Sheet1' sheetId='1' r:id='rId1'/></sheets></workbook>")
            archive.writestr("xl/_rels/workbook.xml.rels", "<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/></Relationships>")
            archive.writestr("xl/sharedStrings.xml", "<?xml version='1.0' encoding='UTF-8'?><sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' count='4' uniqueCount='4'><si><t>manager</t></si><si><t>amount</t></si><si><t>Alice</t></si><si><t>Bob</t></si></sst>")
            archive.writestr("xl/worksheets/sheet1.xml", "<?xml version='1.0' encoding='UTF-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData><row r='1'><c r='A1' t='s'><v>0</v></c><c r='B1' t='s'><v>1</v></c></row><row r='2'><c r='A2' t='s'><v>2</v></c><c r='B2'><v>1200</v></c></row><row r='3'><c r='A3' t='s'><v>3</v></c><c r='B3'><v>3400</v></c></row></sheetData></worksheet>")
        attachment = {"relative_path": "uploads/sales.xlsx", "original_name": "sales.xlsx"}
        loaded = self.backend.load_dashboard_dataset_from_attachment(attachment)
        self.assertIsNotNone(loaded)
        dataset, source_meta = loaded
        self.assertEqual(source_meta["file_type"], "xlsx")
        self.assertEqual(dataset["columns"], ["manager", "amount"])
        self.assertEqual(len(dataset["rows"]), 2)
        self.assertIn("amount", dataset["numeric_columns"])

    def test_it_analytics_dataset_dashboard_uses_dynamic_metrics_and_explanations(self):
        dataset = {
            "rows": [
                {"period": "2026-05", "incident_count": 5.0, "uptime": 99.7, "latency_ms": 180.0, "mttr_hours": 1.2, "service": "api"},
                {"period": "2026-06", "incident_count": 3.0, "uptime": 99.9, "latency_ms": 140.0, "mttr_hours": 0.9, "service": "web"},
                {"period": "2026-07", "incident_count": 7.0, "uptime": 99.4, "latency_ms": 240.0, "mttr_hours": 2.1, "service": "api"},
            ],
            "columns": ["period", "incident_count", "uptime", "latency_ms", "mttr_hours", "service"],
            "numeric_columns": ["incident_count", "uptime", "latency_ms", "mttr_hours"],
            "categorical_columns": ["period", "service"],
        }
        source_meta = {"label": "it_ops.csv", "original_name": "it_ops.csv", "file_type": "csv"}
        payload = self.backend.build_generic_dataset_dashboard_payload(dataset, source_meta, "Сделай дашборд ИТ-аналитики по incidents, uptime, latency и MTTR")
        self.assertEqual(payload["dashboard"]["kind"], "business_function_analytics")
        cards_blob = json.dumps(payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        sections_blob = json.dumps(payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Средняя доступность", cards_blob)
        self.assertIn("MTTR", cards_blob)
        self.assertIn("Типичная задержка", cards_blob)
        self.assertIn("Динамика инцидентов по периодам", sections_blob)
        self.assertIn("Профиль производительности", sections_blob)
        self.assertIn("Показывает, какую долю времени сервисы были доступны пользователю", cards_blob)

    def test_security_dataset_dashboard_uses_dynamic_metrics_and_explanations(self):
        dataset = {
            "rows": [
                {"asset": "srv-1", "vulnerability_count": 12.0, "risk_score": 78.0, "control_coverage": 0.72, "severity": "high"},
                {"asset": "srv-2", "vulnerability_count": 4.0, "risk_score": 42.0, "control_coverage": 0.91, "severity": "medium"},
                {"asset": "srv-3", "vulnerability_count": 18.0, "risk_score": 88.0, "control_coverage": 0.63, "severity": "critical"},
            ],
            "columns": ["asset", "vulnerability_count", "risk_score", "control_coverage", "severity"],
            "numeric_columns": ["vulnerability_count", "risk_score", "control_coverage"],
            "categorical_columns": ["asset", "severity"],
        }
        source_meta = {"label": "security.csv", "original_name": "security.csv", "file_type": "csv"}
        payload = self.backend.build_generic_dataset_dashboard_payload(dataset, source_meta, "Построй security dashboard по vulnerabilities, control coverage и risk")
        self.assertEqual(payload["dashboard"]["kind"], "business_function_analytics")
        cards_blob = json.dumps(payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        sections_blob = json.dumps(payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Бэклог уязвимостей", cards_blob)
        self.assertIn("Покрытие контролей", cards_blob)
        self.assertIn("Средний риск-уровень", cards_blob)
        self.assertIn("Распределение по критичности", sections_blob)
        self.assertIn("какая доля проверяемых требований или активов реально закрыта контролями", cards_blob)

    def test_remaining_business_functions_dataset_dashboards_use_explainable_metrics(self):
        cases = [
            {
                "name": "sales",
                "dataset": {
                    "rows": [
                        {"created_at": "2026-05-01", "manager": "Alice", "stage": "Won", "amount": 1200.0},
                        {"created_at": "2026-06-01", "manager": "Bob", "stage": "Qualified", "amount": 1800.0},
                    ],
                    "columns": ["created_at", "manager", "stage", "amount"],
                    "numeric_columns": ["amount"],
                    "categorical_columns": ["created_at", "manager", "stage"],
                },
                "request": "Построй sales dashboard по выручке, стадиям и менеджерам",
                "card": "Выручка / объём сделок",
                "section": "Динамика продаж по периодам",
            },
            {
                "name": "marketing",
                "dataset": {
                    "rows": [
                        {"period": "2026-05", "channel": "Ads", "leads": 40.0, "cost": 400.0, "conversion_rate": 0.12},
                        {"period": "2026-06", "channel": "Organic", "leads": 25.0, "cost": 120.0, "conversion_rate": 0.18},
                    ],
                    "columns": ["period", "channel", "leads", "cost", "conversion_rate"],
                    "numeric_columns": ["leads", "cost", "conversion_rate"],
                    "categorical_columns": ["period", "channel"],
                },
                "request": "Построй marketing dashboard по leads, cost и conversion",
                "card": "Стоимость лида",
                "section": "Эффективность каналов",
            },
            {
                "name": "finance",
                "dataset": {
                    "rows": [
                        {"period": "2026-05", "category": "Sales", "income": 5000.0, "expense": 3200.0, "budget": 4500.0, "actual": 5000.0},
                        {"period": "2026-06", "category": "Ops", "income": 4700.0, "expense": 2800.0, "budget": 4600.0, "actual": 4700.0},
                    ],
                    "columns": ["period", "category", "income", "expense", "budget", "actual"],
                    "numeric_columns": ["income", "expense", "budget", "actual"],
                    "categorical_columns": ["period", "category"],
                },
                "request": "Сделай finance dashboard по income, expense и budget vs actual",
                "card": "Баланс",
                "section": "Структура финансов по категориям",
            },
            {
                "name": "operations",
                "dataset": {
                    "rows": [
                        {"period": "2026-05", "team": "A", "backlog": 12.0, "cycle_time": 4.5, "throughput": 20.0, "sla_rate": 0.93},
                        {"period": "2026-06", "team": "B", "backlog": 9.0, "cycle_time": 3.8, "throughput": 24.0, "sla_rate": 0.96},
                    ],
                    "columns": ["period", "team", "backlog", "cycle_time", "throughput", "sla_rate"],
                    "numeric_columns": ["backlog", "cycle_time", "throughput", "sla_rate"],
                    "categorical_columns": ["period", "team"],
                },
                "request": "Покажи operations dashboard по backlog, throughput, cycle time и SLA",
                "card": "Бэклог",
                "section": "Операционная динамика по периодам",
            },
            {
                "name": "support",
                "dataset": {
                    "rows": [
                        {"period": "2026-05", "priority": "high", "backlog": 11.0, "first_response_time": 1.8, "resolution_time": 8.0, "sla_breach": 0.08},
                        {"period": "2026-06", "priority": "medium", "backlog": 7.0, "first_response_time": 1.2, "resolution_time": 6.0, "sla_breach": 0.04},
                    ],
                    "columns": ["period", "priority", "backlog", "first_response_time", "resolution_time", "sla_breach"],
                    "numeric_columns": ["backlog", "first_response_time", "resolution_time", "sla_breach"],
                    "categorical_columns": ["period", "priority"],
                },
                "request": "Собери support dashboard по ticket backlog, first response, resolution и SLA",
                "card": "SLA compliance",
                "section": "Backlog по приоритетам",
            },
            {
                "name": "hr",
                "dataset": {
                    "rows": [
                        {"period": "2026-05", "team": "Platform", "headcount": 40.0, "hire_count": 3.0, "attrition": 1.0},
                        {"period": "2026-06", "team": "Product", "headcount": 28.0, "hire_count": 2.0, "attrition": 2.0},
                    ],
                    "columns": ["period", "team", "headcount", "hire_count", "attrition"],
                    "numeric_columns": ["headcount", "hire_count", "attrition"],
                    "categorical_columns": ["period", "team"],
                },
                "request": "Сделай HR dashboard по headcount, hiring и attrition",
                "card": "Headcount",
                "section": "Распределение по командам",
            },
            {
                "name": "product",
                "dataset": {
                    "rows": [
                        {"period": "2026-05", "feature": "Search", "activation_rate": 0.54, "adoption_rate": 0.41, "retention_rate": 0.33, "conversion_rate": 0.12},
                        {"period": "2026-06", "feature": "AI", "activation_rate": 0.61, "adoption_rate": 0.47, "retention_rate": 0.36, "conversion_rate": 0.15},
                    ],
                    "columns": ["period", "feature", "activation_rate", "adoption_rate", "retention_rate", "conversion_rate"],
                    "numeric_columns": ["activation_rate", "adoption_rate", "retention_rate", "conversion_rate"],
                    "categorical_columns": ["period", "feature"],
                },
                "request": "Построй product dashboard по activation, adoption, retention и conversion",
                "card": "Retention",
                "section": "Срез по функциям / сегментам",
            },
            {
                "name": "procurement",
                "dataset": {
                    "rows": [
                        {"period": "2026-05", "vendor": "VendorA", "category": "Cloud", "spend": 3200.0, "lead_time": 12.0, "savings": 140.0},
                        {"period": "2026-06", "vendor": "VendorB", "category": "Hardware", "spend": 2100.0, "lead_time": 18.0, "savings": 90.0},
                    ],
                    "columns": ["period", "vendor", "category", "spend", "lead_time", "savings"],
                    "numeric_columns": ["spend", "lead_time", "savings"],
                    "categorical_columns": ["period", "vendor", "category"],
                },
                "request": "Собери procurement dashboard по spend, lead time, savings и suppliers",
                "card": "Spend",
                "section": "Концентрация spend по поставщикам",
            },
        ]
        for case in cases:
            with self.subTest(function=case["name"]):
                source_meta = {"label": f"{case['name']}.csv", "original_name": f"{case['name']}.csv", "file_type": "csv"}
                payload = self.backend.build_generic_dataset_dashboard_payload(case["dataset"], source_meta, case["request"])
                self.assertEqual(payload["dashboard"]["kind"], "business_function_analytics")
                cards_blob = json.dumps(payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
                sections_blob = json.dumps(payload["dashboard"].get("sections", []), ensure_ascii=False)
                self.assertIn(case["card"], cards_blob)
                self.assertIn(case["section"], sections_blob)
                self.assertIn("note", sections_blob)

    def test_semantic_metric_mapping_v1_for_plan_ratio_ageing_and_cohorts(self):
        finance_dataset = {
            "rows": [
                {"period": "2026-05", "category": "Sales", "budget": 4500.0, "actual": 5000.0},
                {"period": "2026-06", "category": "Ops", "budget": 4600.0, "actual": 4300.0},
            ],
            "columns": ["period", "category", "budget", "actual"],
            "numeric_columns": ["budget", "actual"],
            "categorical_columns": ["period", "category"],
        }
        finance_payload = self.backend.build_generic_dataset_dashboard_payload(finance_dataset, {"label": "finance.csv", "original_name": "finance.csv", "file_type": "csv"}, "finance dashboard plan vs actual")
        finance_cards = json.dumps(finance_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        finance_sections = json.dumps(finance_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Plan vs Actual", finance_cards)
        self.assertIn("относительное отклонение", finance_cards)
        self.assertIn("Plan vs Actual по строкам", finance_sections)

        support_dataset = {
            "rows": [
                {"period": "2026-05", "priority": "high", "resolved": 42.0, "opened": 50.0, "bucket_0-30": 12.0, "bucket_31-60": 7.0, "bucket_61-90": 3.0},
                {"period": "2026-06", "priority": "medium", "resolved": 44.0, "opened": 48.0, "bucket_0-30": 10.0, "bucket_31-60": 5.0, "bucket_61-90": 4.0},
            ],
            "columns": ["period", "priority", "resolved", "opened", "bucket_0-30", "bucket_31-60", "bucket_61-90"],
            "numeric_columns": ["resolved", "opened", "bucket_0-30", "bucket_31-60", "bucket_61-90"],
            "categorical_columns": ["period", "priority"],
        }
        support_payload = self.backend.build_generic_dataset_dashboard_payload(support_dataset, {"label": "support.csv", "original_name": "support.csv", "file_type": "csv"}, "support dashboard resolution rate and ageing")
        support_cards = json.dumps(support_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        support_sections = json.dumps(support_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Inflow vs Outflow", support_cards)
        self.assertIn("Ageing обращений", support_sections)

        product_dataset = {
            "rows": [
                {"cohort": "2026-05", "feature": "Search", "retention": 0.33, "adoption": 0.41},
                {"cohort": "2026-06", "feature": "AI", "retention": 0.36, "adoption": 0.47},
            ],
            "columns": ["cohort", "feature", "retention", "adoption"],
            "numeric_columns": ["retention", "adoption"],
            "categorical_columns": ["cohort", "feature"],
        }
        product_payload = self.backend.build_generic_dataset_dashboard_payload(product_dataset, {"label": "product.csv", "original_name": "product.csv", "file_type": "csv"}, "product retention cohort dashboard")
        product_cards = json.dumps(product_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        product_sections = json.dumps(product_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Retention", product_cards)
        self.assertIn("Retention по когортам / периодам", product_sections)

        procurement_dataset = {
            "rows": [
                {"period": "2026-05", "vendor": "VendorA", "spend": 3200.0, "savings": 140.0, "overdue_0-30": 5.0, "overdue_31-60": 2.0},
                {"period": "2026-06", "vendor": "VendorB", "spend": 2100.0, "savings": 90.0, "overdue_0-30": 4.0, "overdue_31-60": 1.0},
            ],
            "columns": ["period", "vendor", "spend", "savings", "overdue_0-30", "overdue_31-60"],
            "numeric_columns": ["spend", "savings", "overdue_0-30", "overdue_31-60"],
            "categorical_columns": ["period", "vendor"],
        }
        procurement_payload = self.backend.build_generic_dataset_dashboard_payload(procurement_dataset, {"label": "procurement.csv", "original_name": "procurement.csv", "file_type": "csv"}, "procurement spend savings aging dashboard")
        procurement_cards = json.dumps(procurement_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        procurement_sections = json.dumps(procurement_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Savings rate", procurement_cards)
        self.assertIn("Ageing закупок / просрочек", procurement_sections)

    def test_semantic_metric_mapping_v2_for_funnel_flow_and_concentration(self):
        sales_dataset = {
            "rows": [
                {"period": "2026-05", "manager": "Alice", "lead_count": 120.0, "qualified": 60.0, "won": 18.0, "amount": 4500.0},
                {"period": "2026-06", "manager": "Bob", "lead_count": 100.0, "qualified": 50.0, "won": 16.0, "amount": 3900.0},
            ],
            "columns": ["period", "manager", "lead_count", "qualified", "won", "amount"],
            "numeric_columns": ["lead_count", "qualified", "won", "amount"],
            "categorical_columns": ["period", "manager"],
        }
        sales_payload = self.backend.build_generic_dataset_dashboard_payload(sales_dataset, {"label": "sales.csv", "original_name": "sales.csv", "file_type": "csv"}, "sales dashboard funnel")
        sales_cards = json.dumps(sales_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        sales_sections = json.dumps(sales_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Сквозная конверсия воронки", sales_cards)
        self.assertIn("Сквозная воронка продаж", sales_sections)

        operations_dataset = {
            "rows": [
                {"period": "2026-05", "team": "A", "created": 80.0, "completed": 70.0, "backlog": 25.0},
                {"period": "2026-06", "team": "B", "created": 90.0, "completed": 72.0, "backlog": 31.0},
            ],
            "columns": ["period", "team", "created", "completed", "backlog"],
            "numeric_columns": ["created", "completed", "backlog"],
            "categorical_columns": ["period", "team"],
        }
        operations_payload = self.backend.build_generic_dataset_dashboard_payload(operations_dataset, {"label": "ops.csv", "original_name": "ops.csv", "file_type": "csv"}, "operations dashboard flow")
        operations_cards = json.dumps(operations_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        operations_sections = json.dumps(operations_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Inflow vs Outflow", operations_cards)
        self.assertIn("Flow clearance rate", operations_cards)
        self.assertIn("Концентрация нагрузки", operations_sections)

        product_dataset = {
            "rows": [
                {"period": "2026-05", "feature": "Search", "signup": 300.0, "activated": 150.0, "retention": 75.0, "adoption": 0.41},
                {"period": "2026-06", "feature": "AI", "signup": 280.0, "activated": 170.0, "retention": 82.0, "adoption": 0.47},
            ],
            "columns": ["period", "feature", "signup", "activated", "retention", "adoption"],
            "numeric_columns": ["signup", "activated", "retention", "adoption"],
            "categorical_columns": ["period", "feature"],
        }
        product_payload = self.backend.build_generic_dataset_dashboard_payload(product_dataset, {"label": "product-v2.csv", "original_name": "product-v2.csv", "file_type": "csv"}, "product dashboard funnel and concentration")
        product_cards = json.dumps(product_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        product_sections = json.dumps(product_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Продуктовая воронка", product_sections)
        self.assertIn("Срез по функциям / сегментам", product_sections)

        procurement_dataset = {
            "rows": [
                {"period": "2026-05", "vendor": "VendorA", "spend": 7000.0, "savings": 200.0},
                {"period": "2026-06", "vendor": "VendorB", "spend": 1800.0, "savings": 60.0},
                {"period": "2026-06", "vendor": "VendorC", "spend": 1200.0, "savings": 40.0},
            ],
            "columns": ["period", "vendor", "spend", "savings"],
            "numeric_columns": ["spend", "savings"],
            "categorical_columns": ["period", "vendor"],
        }
        procurement_payload = self.backend.build_generic_dataset_dashboard_payload(procurement_dataset, {"label": "procurement-v2.csv", "original_name": "procurement-v2.csv", "file_type": "csv"}, "procurement vendor concentration dashboard")
        procurement_cards = json.dumps(procurement_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        procurement_sections = json.dumps(procurement_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Vendor concentration risk", procurement_cards)
        self.assertIn("Top vendors by spend share", procurement_sections)

    def test_semantic_metric_mapping_v3_for_grouping_units_and_source_shape(self):
        finance_dataset = {
            "rows": [
                {"period": "2026-05", "department": "Sales", "budget": 1000.0, "actual": 1200.0},
                {"period": "2026-05", "department": "Ops", "budget": 900.0, "actual": 850.0},
                {"period": "2026-06", "department": "Sales", "budget": 1100.0, "actual": 1080.0},
                {"period": "2026-06", "department": "Ops", "budget": 950.0, "actual": 990.0},
            ],
            "columns": ["period", "department", "budget", "actual"],
            "numeric_columns": ["budget", "actual"],
            "categorical_columns": ["period", "department"],
        }
        finance_payload = self.backend.build_generic_dataset_dashboard_payload(finance_dataset, {"label": "finance-v3.csv", "original_name": "finance-v3.csv", "file_type": "csv"}, "finance dashboard grouped plan actual")
        finance_sections = json.dumps(finance_payload["dashboard"].get("sections", []), ensure_ascii=False)
        finance_cards = json.dumps(finance_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        self.assertIn("Plan vs Actual по группам", finance_sections)
        self.assertIn("Форма источника", finance_cards)
        self.assertIn("File export", finance_cards)

        normalized = self.backend.normalize_percent_like_values([0.42, 48.0, 0.55])
        self.assertEqual(normalized, [42.0, 48.0, 55.0])

        marketing_dataset = {
            "rows": [
                {"period": "2026-05", "channel": "SEO", "leads": 100.0, "cost": 500.0},
                {"period": "2026-05", "channel": "Ads", "leads": 20.0, "cost": 700.0},
                {"period": "2026-06", "channel": "SEO", "leads": 80.0, "cost": 450.0},
                {"period": "2026-06", "channel": "Partners", "leads": 10.0, "cost": 120.0},
            ],
            "columns": ["period", "channel", "leads", "cost"],
            "numeric_columns": ["leads", "cost"],
            "categorical_columns": ["period", "channel"],
        }
        marketing_payload = self.backend.build_generic_dataset_dashboard_payload(marketing_dataset, {"label": "marketing-v3.csv", "original_name": "marketing-v3.csv", "file_type": "csv"}, "marketing dashboard grouped concentration")
        marketing_sections = json.dumps(marketing_payload["dashboard"].get("sections", []), ensure_ascii=False)
        self.assertIn("Концентрация каналов по периодам", marketing_sections)

        procurement_dataset = {
            "rows": [
                {"category": "Infra", "vendor": "A", "spend": 5000.0},
                {"category": "Infra", "vendor": "B", "spend": 800.0},
                {"category": "Software", "vendor": "C", "spend": 2500.0},
                {"category": "Software", "vendor": "D", "spend": 400.0},
            ],
            "columns": ["category", "vendor", "spend"],
            "numeric_columns": ["spend"],
            "categorical_columns": ["category", "vendor"],
        }
        procurement_payload = self.backend.build_generic_dataset_dashboard_payload(procurement_dataset, {"label": "web_research_procurement", "original_name": "web_research_procurement", "file_type": "json"}, "procurement dashboard grouped vendor concentration")
        procurement_sections = json.dumps(procurement_payload["dashboard"].get("sections", []), ensure_ascii=False)
        procurement_cards = json.dumps(procurement_payload["dashboard"].get("summary_cards", []), ensure_ascii=False)
        self.assertIn("Vendor concentration across slices", procurement_sections)
        self.assertIn("Web structured", procurement_cards)
        self.assertIn("source shape: web_structured", procurement_payload["dashboard"]["subtitle"])

    def test_infer_business_dashboard_function_distinguishes_marketing(self):
        function_name = self.backend.infer_business_dashboard_function(
            "Построй дашборд маркетинга по каналам и campaign performance",
            ["channel", "campaign", "leads", "cost"],
        )
        self.assertEqual(function_name, "marketing")
        spec = self.backend.build_business_function_spec(function_name)
        self.assertEqual(spec["label"], "Маркетинг")
        self.assertIn("cost_efficiency", spec.get("metric_groups", []))
        self.assertIn("campaign", spec.get("column_markers", []))

    def test_business_dashboard_function_policy_is_loaded_and_used_in_prompt(self):
        spec = self.backend.build_business_function_spec("finance")
        self.assertEqual(spec["label"], "Финансы")
        self.assertIn("plan_vs_actual", spec.get("metric_groups", []))
        prompt = self.backend.build_global_dashboard_prompt(
            "Построй дашборд финансов по доходам, расходам и budget vs actual",
            {"label": "web_research"},
            {"source_mode": "global_only", "notes": ""},
        )
        self.assertIn("Функциональный фокус: Финансы", prompt)
        self.assertIn("plan_vs_actual", prompt)
        self.assertIn("Функциональная инструкция", prompt)
        self.assertIn("income, expenses, margin", prompt)
        self.assertIn("Reference guidance layer", prompt)

    def test_dashboard_reference_layer_exposes_review_and_finance_grammar(self):
        refs = self.backend.get_dashboard_grammar_reference()
        self.assertIn("dashboard_semantic_core", refs)
        self.assertIn("dashboard_review", refs)
        self.assertIn("dashboard_finance", refs)
        self.assertEqual(refs["dashboard_review"]["intent"], "review")
        guidance = self.backend.build_dashboard_reference_guidance("review", "finance")
        self.assertIn("budget vs actual", guidance)
        self.assertIn("обзор", guidance.lower())
        self.assertIn("source shape", guidance)

    def test_extended_business_function_policy_covers_ops_support_hr_product_procurement_it_and_security(self):
        cases = [
            (
                "Построй operations dashboard по SLA, backlog и cycle time",
                ["sla", "throughput", "cycle", "backlog", "queue"],
                "operations",
                "throughput",
            ),
            (
                "Покажи дашборд поддержки по ticket backlog, first response и SLA breaches",
                ["ticket", "response", "resolution", "backlog", "priority"],
                "support",
                "response_time",
            ),
            (
                "Собери HR dashboard по headcount, hiring funnel и attrition",
                ["employee", "candidate", "hire", "termination", "team"],
                "hr",
                "candidate_funnel",
            ),
            (
                "Сделай продуктовый дашборд по activation, feature adoption и retention",
                ["feature", "activation", "usage", "retention", "cohort"],
                "product",
                "feature_adoption",
            ),
            (
                "Собери procurement dashboard по spend, suppliers и lead time",
                ["vendor", "supplier", "spend", "lead time", "category"],
                "procurement",
                "vendor_concentration",
            ),
            (
                "Сделай дашборд ИТ-аналитики по incidents, uptime, latency и MTTR",
                ["incident", "uptime", "latency", "mttr", "service"],
                "it_analytics",
                "availability",
            ),
            (
                "Построй security dashboard по vulnerabilities, incidents и control coverage",
                ["vulnerability", "severity", "control", "incident", "asset"],
                "security",
                "control_coverage",
            ),
        ]
        for text, columns, expected_function, expected_metric_group in cases:
            with self.subTest(expected_function=expected_function):
                function_name = self.backend.infer_business_dashboard_function(text, columns)
                self.assertEqual(function_name, expected_function)
                spec = self.backend.build_business_function_spec(function_name)
                self.assertIn(expected_metric_group, spec.get("metric_groups", []))

    def test_extended_dashboard_reference_layer_includes_it_and_security_guidance(self):
        refs = self.backend.get_dashboard_grammar_reference()
        self.assertIn("dashboard_operations", refs)
        self.assertIn("dashboard_support", refs)
        self.assertIn("dashboard_hr", refs)
        self.assertIn("dashboard_product", refs)
        self.assertIn("dashboard_procurement", refs)
        self.assertIn("dashboard_it_analytics", refs)
        self.assertIn("dashboard_security", refs)
        it_guidance = self.backend.build_dashboard_reference_guidance("review", "it_analytics")
        security_guidance = self.backend.build_dashboard_reference_guidance("review", "security")
        self.assertIn("MTTR", it_guidance)
        self.assertIn("severity", security_guidance)

    def test_global_dashboard_prompt_uses_it_and_security_function_guidance(self):
        it_prompt = self.backend.build_global_dashboard_prompt(
            "Сделай дашборд ИТ-аналитики по incidents, uptime, latency и MTTR",
            {"label": "web_research"},
            {"source_mode": "global_only", "notes": ""},
        )
        self.assertIn("Функциональный фокус: ИТ-аналитика", it_prompt)
        self.assertIn("incident_volume", it_prompt)
        self.assertIn("MTTR", it_prompt)

        security_prompt = self.backend.build_global_dashboard_prompt(
            "Построй security dashboard по vulnerabilities, incidents и control coverage",
            {"label": "web_research"},
            {"source_mode": "global_only", "notes": ""},
        )
        self.assertIn("Функциональный фокус: Безопасность", security_prompt)
        self.assertIn("control_coverage", security_prompt)
        self.assertIn("severity", security_prompt)

    def test_normalize_external_dashboard_payload_drops_english_and_synthetic_sections_for_russian_request(self):
        payload = self.backend.normalize_external_dashboard_payload(
            {
                "title": "Business Intelligence Development Overview",
                "subtitle": "Key facts and trends",
                "summary_cards": [{"label": "Definition", "value": "Business Intelligence", "note": "Wikipedia"}],
                "sections": [
                    {
                        "kind": "bar_list",
                        "title": "BI Adoption by Enterprise Size (illustrative)",
                        "note": "Indicative averages",
                        "items": [
                            {"label": "Small", "value": "35", "ratio": 0.35},
                            {"label": "Medium", "value": "45", "ratio": 0.45},
                        ],
                    },
                    {
                        "kind": "text_list",
                        "title": "Key Trends",
                        "items": [{"text": "Integration of AI/ML", "meta": "Trend"}],
                    },
                ],
                "notes": "Illustrative estimates",
                "sources": [{"label": "Wikipedia", "url": "https://example.com"}],
            },
            "Illustrative overview",
            {"label": "web_research"},
            {"source_mode": "global_only"},
            "Собери дашборд по истории развития BI",
        )
        self.assertEqual(payload["intent"], "history_evolution")
        self.assertEqual(payload["notes"], "")
        self.assertTrue(all(section["kind"] in {"text_list", "timeline_list", "matrix_list"} for section in payload["sections"]))
        self.assertTrue(all(any(ord(ch) > 127 for ch in (section.get("title") or "")) for section in payload["sections"]))
        self.assertTrue(all(any(ord(ch) > 127 for ch in card["label"]) for card in payload["summary_cards"]))

    def test_extract_json_object_accepts_dirty_llm_wrapper(self):
        payload = self.backend.extract_json_object(
            "Вот структурированный результат.\n```json\n{\"reply_text\": \"Готово\", \"dashboard\": {\"title\": \"BI\", \"sections\": [{\"kind\": \"text_list\", \"title\": \"Что удалось установить\", \"items\": [\"Пункт\"]}]}}\n```\nЕсли нужно, уточню детали."
        )
        self.assertEqual(payload["reply_text"], "Готово")
        self.assertEqual(payload["dashboard"]["title"], "BI")

    def test_build_global_dashboard_reply_tolerates_wrapped_json_response(self):
        original = self.backend.call_hermes_messages
        try:
            def fake_call(messages, model_name=None):
                return (
                    "Сначала короткое пояснение.\n```json\n{\"reply_text\": \"Собрала дашборд\", \"dashboard\": {\"title\": \"История BI\", \"summary_cards\": [{\"label\": \"Режим\", \"value\": \"global_only\"}], \"sections\": [{\"kind\": \"timeline_list\", \"title\": \"Этапы\", \"items\": [{\"label\": \"DSS\", \"value\": \"Ранние системы поддержки решений\"}]}, {\"kind\": \"matrix_list\", \"title\": \"Смена практик\", \"items\": [{\"label\": \"Отчётность\", \"value\": \"Self-service BI\"}]}, {\"kind\": \"text_list\", \"title\": \"Вывод\", \"items\": [\"BI развивался волнами\"]}], \"sources\": [{\"label\": \"Wikipedia\", \"url\": \"https://example.com\"}]}}\n```\nХвост ответа.",
                    {"model": model_name or "fake"},
                )
            self.backend.call_hermes_messages = fake_call
            reply_text, meta = self.backend.build_global_dashboard_reply(
                "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик",
                {"label": "Интернет", "item_key": "web_research", "route": "web_research"},
                {"source_mode": "global_only", "notes": ""},
            )
        finally:
            self.backend.call_hermes_messages = original

        self.assertIn("дашборд", reply_text.lower())
        self.assertEqual(meta["message_kind"], "dashboard_result")
        self.assertEqual(meta["dashboard"]["intent"], "history_evolution")
        self.assertGreaterEqual(len(meta["dashboard"].get("sections", [])), 3)

    def test_collection_dashboard_reply_forces_russian_reply_text_when_model_returns_english(self):
        original = self.backend.call_hermes_messages
        try:
            def fake_call(messages, model_name=None):
                return (
                    "Wrapped prefix ```json {\"reply_text\": \"Here is a dashboard summary\", \"dashboard\": {\"title\": \"Internet research\", \"sections\": [{\"kind\": \"text_list\", \"title\": \"Findings\", \"items\": [\"Point\"]}]}} ``` suffix",
                    {"model": model_name or "fake"},
                )
            self.backend.call_hermes_messages = fake_call
            reply_text, meta = self.backend.maybe_build_collection_dashboard_reply(
                {
                    "output_format": "dashboard",
                    "source_kind": "web",
                    "request_text": "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик",
                    "subject": "BI",
                    "analysis_modes": ["history"],
                },
                [{"requested_url": "https://example.com", "final_url": "https://example.com", "title": "Example", "text": "BI history"}],
                [{"period": "1990s", "event": "OLAP"}],
                downstream="dashboard:web_collection_result",
            )
        finally:
            self.backend.call_hermes_messages = original

        self.assertTrue(any(ord(ch) > 127 for ch in reply_text))
        self.assertIn("дашборд", reply_text.lower())
        self.assertEqual(meta["message_kind"], "dashboard_result")
        self.assertEqual(meta["downstream"], "dashboard:web_collection_result")

    def test_historical_bi_request_uses_history_evolution_blueprint(self):
        intent = self.backend.infer_external_dashboard_intent("Собери дашборд по истории развития BI-решений и BI-практик")
        self.assertEqual(intent, "history_evolution")
        blueprint = self.backend.build_external_dashboard_blueprint(intent)
        self.assertEqual(blueprint["visual_sections"], ["timeline_list", "matrix_list"])
        self.assertLess(blueprint["priority_blocks"].index("timeline_list"), blueprint["priority_blocks"].index("bar_list"))

        prompt = self.backend.build_global_dashboard_prompt(
            "Собери дашборд по истории развития BI-решений и BI-практик",
            {"label": "web_research"},
            {"source_mode": "global_only", "notes": ""},
        )
        self.assertIn("только на русском", prompt)
        self.assertIn("не рисуй synthetic charts", prompt)
        self.assertIn("timeline_list и/или matrix_list", prompt)

    def test_review_intent_is_used_for_overview_request_and_includes_reference_guidance(self):
        intent = self.backend.infer_external_dashboard_intent("Сделай обзор BI: что это такое, как устроен и как развивался")
        self.assertEqual(intent, "review")
        blueprint = self.backend.build_external_dashboard_blueprint(intent)
        self.assertEqual(blueprint["visual_sections"], ["timeline_list", "matrix_list"])
        prompt = self.backend.build_global_dashboard_prompt(
            "Сделай обзор BI: что это такое, как устроен и как развивался",
            {"label": "web_research"},
            {"source_mode": "global_only", "notes": ""},
        )
        self.assertIn("Reference goal", prompt)
        self.assertIn("review", prompt)
        self.assertIn("обзор темы", prompt)

    def test_market_overview_synthesis_fallback_avoids_practices_bias(self):
        contract = {
            "request_text": "Проанализируй рынок автомобилей Geely в России в 2024-2025 годах и построй дашборд",
            "subject": "рынок автомобилей Geely в России в 2024-2025 годах",
            "output_format": "dashboard",
            "source_kind": "web",
            "source_label": "Интернет-исследование",
        }
        synthesis = self.backend.build_collection_synthesis_fallback_text(
            contract,
            [{"title": "Geely Russia", "final_url": "https://example.com/geely", "requested_url": "https://example.com/geely", "text": "Geely усиливает позиции в России, расширяет модельный ряд и локальное присутствие. Основные сигналы рынка связаны с конкуренцией китайских брендов, ценовым позиционированием и доступностью моделей."}],
            [],
        )
        self.assertIn("обзор рынка", synthesis.lower())
        self.assertIn("рыночный сигнал 1", synthesis.lower())
        self.assertNotIn("этап 1", synthesis.lower())

        payload = self.backend.build_dashboard_from_synthesis_fallback_payload(contract, synthesis, {"label": "Интернет-исследование"})
        sections = payload["dashboard"]["sections"]
        self.assertEqual(sections[0]["kind"], "bar_list")
        self.assertIn("рыночные акценты", sections[0]["title"].lower())
        self.assertNotIn("практик и подходов", json.dumps(sections, ensure_ascii=False).lower())

    def test_history_fallback_avoids_duplicate_focus_repetition(self):
        contract = {
            "request_text": "Собери дашборд по истории развития BI-решений",
            "subject": "история развития BI-решений",
            "output_format": "dashboard",
            "source_kind": "web",
            "source_label": "Интернет-исследование",
        }
        synthesis = """Ранний этап BI был связан с DSS и статической отчётностью.

Затем рынок сместился к хранилищам данных и OLAP.

Позже компании перешли к self-service BI и более широкому кругу пользователей.

Отдельный сдвиг заключался в переходе от отчётности к embedded analytics и data products."""
        payload = self.backend.build_dashboard_from_synthesis_fallback_payload(contract, synthesis, {"label": "Интернет-исследование"})
        sections = payload["dashboard"]["sections"]
        timeline = next(section for section in sections if section["kind"] == "timeline_list")
        matrix = next(section for section in sections if section["kind"] == "matrix_list")
        self.assertTrue(all(item["label"].startswith("Этап") for item in timeline["items"]))
        self.assertTrue(all(item["label"].startswith("Сдвиг") for item in matrix["items"]))
        timeline_values = {item["value"] for item in timeline["items"]}
        matrix_values = {item["value"] for item in matrix["items"]}
        self.assertTrue(matrix_values.isdisjoint(timeline_values))
        self.assertNotIn("фокус 1", json.dumps(matrix, ensure_ascii=False).lower())

    def test_short_dashboard_problem_followup_reuses_previous_dashboard_topic(self):
        user_id = self.create_user("victoria-followup@demo.local")
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "BI dashboard",
            [
                ("user", "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик", {"user_text": "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик"}),
                ("assistant", "Черновой дашборд", {"message_kind": "dashboard_result", "dashboard": {"title": "Интернет-исследование", "sections": [{"kind": "text_list", "title": "Черновик", "items": ["text"]}]}}),
                ("user", "А где сам дашборд ?", {"user_text": "А где сам дашборд ?"}),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
        effective = self.backend.infer_dashboard_followup_request_text(rows, message_ids[-1], "А где сам дашборд ?")
        self.assertIn("истории развития BI", effective)
        self.assertNotEqual(effective, "А где сам дашборд ?")

    def test_dashboard_rerun_followup_reuses_previous_dashboard_topic(self):
        user_id = self.create_user("victoria-rerun@demo.local")
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "BI dashboard rerun",
            [
                ("user", "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик", {"user_text": "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик"}),
                ("assistant", "Черновой дашборд", {"message_kind": "dashboard_result", "dashboard": {"title": "Интернет-исследование", "sections": [{"kind": "text_list", "title": "Черновик", "items": ["text"]}]}}),
                ("user", "Построй снова дашборд, теперь с информацией", {"user_text": "Построй снова дашборд, теперь с информацией"}),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
        effective = self.backend.infer_dashboard_followup_request_text(rows, message_ids[-1], "Построй снова дашборд, теперь с информацией")
        self.assertIn("истории развития BI", effective)
        self.assertNotEqual(effective, "Построй снова дашборд, теперь с информацией")

    def test_process_chat_task_routes_dashboard_rerun_followup_back_to_collection_execution(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "BI dashboard rerun process",
            [
                ("user", "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик", {"user_text": "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик"}),
                ("assistant", "Черновой дашборд", {"message_kind": "dashboard_result", "dashboard": {"title": "Интернет-исследование", "sections": [{"kind": "text_list", "title": "Черновик", "items": ["text"]}]}}),
                ("user", "Построй снова дашборд, теперь с информацией", {"user_text": "Построй снова дашборд, теперь с информацией"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[2], message_ids[3], '{}', ts),
            )
            task_id = int(cur.fetchone()[0])

        original_contract = self.backend.build_collection_clarification_or_contract_reply
        original_execute = self.backend.maybe_execute_collection_request
        original_dashboard = self.backend.maybe_build_dashboard_reply
        captured = {}
        try:
            def fake_contract(text, attachments=None):
                captured['contract_text'] = text
                if "истории развития BI" in text:
                    return (
                        "contract",
                        {"message_kind": "collection_contract", "collection_contract": {"source_kind": "web", "output_format": "dashboard", "subject": "BI", "request_text": text, "missing_fields": []}},
                    )
                return None

            def fake_execute(conn, task, user_row, message_rows, user_text, attachments=None):
                captured['execute_text'] = user_text
                return (
                    "Собрала дашборд по BI",
                    {"message_kind": "dashboard_result", "downstream": "dashboard:web_collection_result", "dashboard": {"title": "Интернет-исследование", "sections": [{"kind": "text_list", "title": "Что удалось установить", "items": ["ok"]}]}}
                )

            def fake_dashboard(*args, **kwargs):
                raise AssertionError("generic dashboard route should not be used for rerun followup")

            self.backend.build_collection_clarification_or_contract_reply = fake_contract
            self.backend.maybe_execute_collection_request = fake_execute
            self.backend.maybe_build_dashboard_reply = fake_dashboard
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.build_collection_clarification_or_contract_reply = original_contract
            self.backend.maybe_execute_collection_request = original_execute
            self.backend.maybe_build_dashboard_reply = original_dashboard

        self.assertIn("истории развития BI", captured.get("contract_text", ""))
        self.assertIn("истории развития BI", captured.get("execute_text", ""))
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (message_ids[3],)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'dashboard_result')
        self.assertEqual(meta['downstream'], 'dashboard:web_collection_result')

    def test_transform_to_dashboard_followup_detects_po_etoi_teme(self):
        self.assertTrue(self.backend.is_transform_to_dashboard_followup('Построй дашборд по этой теме'))
        self.assertTrue(self.backend.is_transform_to_dashboard_followup('Сделай дашборд на основе этого'))
        self.assertFalse(self.backend.is_transform_to_dashboard_followup('Построй дашборд по рынку BI за 2024'))

    def test_collection_dashboard_reply_uses_synthesis_first_for_history_requests(self):
        original = self.backend.call_hermes_messages
        calls = []
        try:
            def fake_call(messages, model_name=None):
                calls.append(messages)
                if len(calls) == 1:
                    return (
                        'BI развивался от DSS и OLAP к enterprise-хранилищам, затем к self-service BI и современным data platforms. На каждом этапе менялись и инструменты, и роль бизнеса в аналитике.',
                        {'model': model_name or 'fake'},
                    )
                return (
                    '{"reply_text":"Собрала содержательный дашборд по истории BI.","dashboard":{"title":"История BI","summary_cards":[{"label":"Этапов","value":"4","note":"по собранному материалу"}],"sections":[{"kind":"timeline_list","title":"Ключевые этапы","items":[{"label":"DSS","value":"Ранние системы поддержки решений"},{"label":"OLAP","value":"Переход к многомерной аналитике"}]},{"kind":"matrix_list","title":"Смена практик","items":[{"label":"ИТ-центричность","value":"Self-service BI"},{"label":"Отчётность","value":"Data-driven decision making"}]},{"kind":"text_list","title":"Выводы","items":["История BI шла через смену роли данных и пользователей."]}]}}',
                    {'model': model_name or 'fake'},
                )
            self.backend.call_hermes_messages = fake_call
            reply_text, meta = self.backend.maybe_build_collection_dashboard_reply(
                {
                    'output_format': 'dashboard',
                    'source_kind': 'api',
                    'request_text': 'Построй дашборд по истории BI-инструментов и BI-практик',
                    'subject': 'BI',
                    'analysis_modes': ['analysis'],
                    'task_layers': {'root_class': 'data_pipeline', 'stages': ['acquisition', 'analysis', 'synthesis', 'delivery']},
                },
                [{'requested_url': 'https://example.com', 'final_url': 'https://example.com', 'title': 'BI history', 'text': 'DSS, OLAP, self-service BI, modern data platforms'}],
                [{'period': '1990s', 'event': 'OLAP'}],
                downstream='dashboard:api_collection_result',
            )
        finally:
            self.backend.call_hermes_messages = original

        self.assertEqual(len(calls), 2)
        self.assertIn('synthesis-stage', calls[0][0]['content'])
        self.assertIn('synthesis_text', calls[1][1]['content'])
        self.assertIn('Собрала содержательный дашборд', reply_text)
        self.assertEqual(meta['message_kind'], 'dashboard_result')
        self.assertTrue(meta.get('collection_synthesis_text'))
        self.assertEqual(meta['dashboard']['intent'], 'history_evolution')

    def test_previous_answer_transform_builds_dashboard_from_collected_text(self):
        user_id = self.create_user('victoria-transform@demo.local')
        thread_id, _ = self.create_thread_with_messages(
            user_id,
            'Новый чат',
            [
                ('user', 'Проанализируй и расскажи кратко историю BI-инструментов и BI-практик', {'user_text': 'Проанализируй и расскажи кратко историю BI-инструментов и BI-практик'}),
                ('assistant', 'BI начинался как DSS и OLAP для управленческой отчётности. Затем появились корпоративные хранилища данных, self-service BI и переход к более широкой data-практике. Со временем сместился и центр тяжести: от ИТ-отчётности к повседневному использованию аналитики бизнесом. В современных практиках BI всё чаще живёт рядом с data platform, governance и продуктовой аналитикой.', {}),
                ('user', 'Построй дашборд по этой теме', {'user_text': 'Построй дашборд по этой теме'}),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute('SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC', (thread_id,)).fetchall()

        original = self.backend.call_hermes_messages
        try:
            def fake_call(messages, model_name=None):
                return (
                    '{"reply_text":"Собрала дашборд по ранее собранному материалу.","dashboard":{"title":"История BI","summary_cards":[{"label":"Источник","value":"предыдущий ответ"}],"sections":[{"kind":"timeline_list","title":"Этапы","items":[{"label":"DSS","value":"Ранний этап"},{"label":"Self-service BI","value":"Расширение роли бизнеса"}]},{"kind":"matrix_list","title":"Смена практик","items":[{"label":"ИТ","value":"Бизнес"},{"label":"Отчётность","value":"Повседневная аналитика"}]},{"kind":"text_list","title":"Вывод","items":["BI эволюционировал вместе с практиками использования данных."]}]}}',
                    {'model': model_name or 'fake'},
                )
            self.backend.call_hermes_messages = fake_call
            reply_text, meta = self.backend.maybe_build_dashboard_from_previous_answer(rows, 'Построй дашборд по этой теме')
        finally:
            self.backend.call_hermes_messages = original

        self.assertIn('ранее собранному материалу', reply_text)
        self.assertEqual(meta['dashboard_builder'], 'previous_answer_transform_dashboard')
        self.assertEqual(meta['downstream'], 'dashboard:previous_answer_transform')
        self.assertEqual(meta['focused_followup_context']['followup_text'], 'Построй дашборд по этой теме')

    def test_process_chat_task_prefers_previous_answer_transform_over_collection_route(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        user_id = int(user_row['id'])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            'BI transform process',
            [
                ('user', 'Проанализируй и расскажи кратко историю BI-инструментов и BI-практик', {'user_text': 'Проанализируй и расскажи кратко историю BI-инструментов и BI-практик'}),
                ('assistant', 'BI начинался как DSS и OLAP. Затем появились корпоративные хранилища данных, self-service BI и современная data platform. Практики сместились от ИТ-отчётности к повседневной работе бизнеса с данными.', {}),
                ('user', 'Построй дашборд по этой теме', {'user_text': 'Построй дашборд по этой теме'}),
                ('assistant', '⏳', {'pending': True, 'processing_status': 'pending'}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[2], message_ids[3], '{}', ts),
            )
            task_id = int(cur.fetchone()[0])

        original_transform = self.backend.maybe_build_dashboard_from_previous_answer
        original_contract = self.backend.build_collection_clarification_or_contract_reply
        captured = {}
        try:
            def fake_transform(message_rows, user_text):
                captured['transform_text'] = user_text
                return ('Готово. Дашборд собран.', {'message_kind': 'dashboard_result', 'downstream': 'dashboard:previous_answer_transform', 'dashboard': {'title': 'История BI', 'sections': [{'kind': 'text_list', 'title': 'ok', 'items': ['ok']}]}})

            def fake_contract(*args, **kwargs):
                raise AssertionError('collection route should not win over previous-answer transform')

            self.backend.maybe_build_dashboard_from_previous_answer = fake_transform
            self.backend.build_collection_clarification_or_contract_reply = fake_contract
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.maybe_build_dashboard_from_previous_answer = original_transform
            self.backend.build_collection_clarification_or_contract_reply = original_contract

        self.assertEqual(captured.get('transform_text'), 'Построй дашборд по этой теме')

    def test_plain_history_dashboard_request_is_treated_as_web_collection(self):
        text = 'Построй дашборд по истории BI-инструментов и BI-практик'
        self.assertTrue(self.backend.looks_like_collection_request(text))
        contract = self.backend.build_collection_contract_meta(text, None)
        self.assertEqual(contract.get('source_kind'), 'web')
        self.assertEqual(contract.get('output_format'), 'dashboard')
        self.assertTrue(contract.get('subject'))
        profile = self.backend.build_collection_search_profile(contract)
        self.assertTrue(any('business intelligence' in phrase.lower() for phrase in (profile.get('subject_phrases') or [])))
        self.assertTrue(any(phrase.lower() == 'business intelligence' for phrase in (profile.get('subject_phrases') or [])))
        queries = self.backend.build_web_search_queries(contract)
        self.assertTrue(any('business intelligence' in query.lower() for query in queries))
        self.assertTrue(any('business intelligence' in query.lower() for query in queries[:3]))

    def test_message_export_supports_extended_formats(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Экспорт ответа",
            [
                ("user", "Собери краткую памятку.", {}),
                (
                    "assistant",
                    "Готово.\n- Первый шаг\n- Второй шаг",
                    {
                        "dashboard": {
                            "title": "Мини-дашборд",
                            "summary_cards": [{"label": "Статус", "value": "готово", "note": "smoke"}],
                            "sections": [{"title": "Шаги", "items": ["Первый шаг", "Второй шаг"]}],
                        }
                    },
                ),
            ],
        )
        assistant_message_id = message_ids[-1]

        txt_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=txt",
            headers=self.auth_headers(token),
        )
        self.assertEqual(txt_response.status_code, 200)
        self.assertIn("text/plain", txt_response.headers.get("Content-Type", ""))
        self.assertIn("Первый шаг", txt_response.get_data(as_text=True))

        md_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=md",
            headers=self.auth_headers(token),
        )
        self.assertEqual(md_response.status_code, 200)
        self.assertIn("text/markdown", md_response.headers.get("Content-Type", ""))
        self.assertIn("## Дашборд", md_response.get_data(as_text=True))

        html_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=html",
            headers=self.auth_headers(token),
        )
        self.assertEqual(html_response.status_code, 200)
        self.assertIn("text/html", html_response.headers.get("Content-Type", ""))
        self.assertIn("<!doctype html>", html_response.get_data(as_text=True).lower())

        pptx_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=pptx",
            headers=self.auth_headers(token),
        )
        self.assertEqual(pptx_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.presentationml.presentation", pptx_response.headers.get("Content-Type", ""))
        with zipfile.ZipFile(io.BytesIO(pptx_response.get_data())) as archive:
            slide_xml = archive.read("ppt/slides/slide2.xml").decode("utf-8", "ignore")
        self.assertIn("Первый шаг", slide_xml)

    def test_message_export_csv_uses_tabular_payload_for_table_result(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Табличный экспорт",
            [
                ("user", "Собери таблицу.", {}),
                (
                    "assistant",
                    "Сводная таблица готова.",
                    {
                        "message_kind": "chat_response",
                        "structured_result": {
                            "summary": "Сводная таблица",
                            "columns": ["Вендор", "Выручка"],
                            "rows": [["A", "10"], ["B", "20"]],
                        },
                    },
                ),
            ],
        )
        assistant_message_id = message_ids[-1]

        csv_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=csv",
            headers=self.auth_headers(token),
        )
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response.headers.get("Content-Type", ""))
        lines = csv_response.get_data(as_text=True).splitlines()
        self.assertEqual(lines[0], 'Вендор,Выручка')
        self.assertEqual(lines[1], 'A,10')
        self.assertEqual(lines[2], 'B,20')

    def test_message_export_pptx_includes_table_slide_for_table_result(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Табличный экспорт в PPTX",
            [
                ("user", "Собери таблицу.", {}),
                (
                    "assistant",
                    "Сводная таблица готова.",
                    {
                        "message_kind": "chat_response",
                        "structured_result": {
                            "summary": "Сводная таблица",
                            "columns": ["Вендор", "Выручка"],
                            "rows": [["A", "10"], ["B", "20"]],
                        },
                    },
                ),
            ],
        )
        assistant_message_id = message_ids[-1]

        pptx_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=pptx",
            headers=self.auth_headers(token),
        )
        self.assertEqual(pptx_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.presentationml.presentation", pptx_response.headers.get("Content-Type", ""))
        with zipfile.ZipFile(io.BytesIO(pptx_response.get_data())) as archive:
            xml_parts = {
                name: archive.read(name).decode("utf-8", "ignore")
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide")
            }
        joined = "\n".join(xml_parts.values())
        self.assertIn("Сводная таблица", joined)
        self.assertIn("Вендор", joined)
        self.assertIn("Выручка", joined)
        self.assertIn("A", joined)
        self.assertIn("10", joined)

    def test_generate_and_attach_file_request_detects_presentation_intent(self):
        text = "Сделай презентацию в pptx по итогам интервью"
        self.assertEqual(self.backend.detect_message_export_format(text), "pptx")
        self.assertTrue(self.backend.is_generate_and_attach_file_request(text))

    def test_infer_clarification_followup_restores_pptx_generation_request(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "PPTX clarification",
            [
                ("user", "Сделай презентацию в pptx по итогам интервью с клиентом", {}),
                (
                    "assistant",
                    "Уточни, пожалуйста, на сколько слайдов и какой акцент нужен.",
                    {"message_kind": "clarification_request", "downstream": "chat:general_clarification"},
                ),
                ("user", "8 слайдов, акцент на выводы и риски", {}),
            ],
        )
        with self.backend.db_connect() as conn:
            message_rows = conn.execute(
                "SELECT * FROM messages WHERE thread_id = (SELECT thread_id FROM messages WHERE id = ?) ORDER BY id ASC",
                (message_ids[-1],),
            ).fetchall()

        restored = self.backend.infer_clarification_followup_request_text(message_rows, message_ids[-1], "8 слайдов, акцент на выводы и риски")
        self.assertIn("pptx", restored.lower())
        self.assertTrue(self.backend.is_generate_and_attach_file_request(restored))
        self.assertEqual(self.backend.detect_message_export_format(restored), "pptx")

    def test_infer_generated_file_followup_restores_source_request_for_slide_page_table_followups(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "ITFM followup restore",
            [
                ("user", "Сделай презентацию в pptx по итогам обсуждения ITFM: проблема, целевая архитектура, этапы внедрения, риски и рекомендации", {"user_text": "Сделай презентацию в pptx по итогам обсуждения ITFM: проблема, целевая архитектура, этапы внедрения, риски и рекомендации"}),
                ("assistant", "Текст по слайдам подготовлен", {"message_kind": "chat_response"}),
                ("user", "По слайдам", {"user_text": "По слайдам"}),
            ],
        )
        with self.backend.db_connect() as conn:
            message_rows = conn.execute(
                "SELECT * FROM messages WHERE thread_id = (SELECT thread_id FROM messages WHERE id = ?) ORDER BY id ASC",
                (message_ids[-1],),
            ).fetchall()

        restored = self.backend.infer_generated_file_followup_request_text(message_rows, message_ids[-1], "По слайдам")
        self.assertIn("itfm", restored.lower())
        self.assertIn("pptx", restored.lower())
        self.assertIn("по слайдам", restored.lower())
        self.assertTrue(self.backend.is_generate_and_attach_file_request(restored))

    def test_parse_presentation_slide_markers_as_headings_for_pptx_export(self):
        text = (
            "Слайд 1: Титульный\n"
            "**Тема презентации:** Бизнес‑интеллект (BI)\n"
            "**Подготовлено для:** руководства\n\n"
            "---\n\n"
            "Слайд 2: Определение BI\n"
            "**Бизнес‑интеллект** – это комплекс методологий и технологий.\n"
            "**Ключевые элементы BI:**\n"
            "- источники данных\n"
            "- слой интеграции\n\n"
            "---\n\n"
            "Слайд 3: Зачем нужно BI\n"
            "- Поддержка принятия решений\n"
            "- Объединение внутренних и внешних данных\n"
        )
        source = self.backend.extract_presentation_source_from_thread(text, "BI")
        plan = self.backend.build_presentation_plan(source)

        section_titles = [item.get("title") for item in plan if item.get("kind") not in {"title", "overview"}]
        self.assertNotIn("Титульный", source.get("overview_titles"))
        self.assertIn("Определение BI", source.get("overview_titles"))
        self.assertIn("Зачем нужно BI", source.get("overview_titles"))
        self.assertNotIn("Титульный", section_titles)
        self.assertIn("Определение BI", section_titles)
        self.assertNotIn("Ключевые элементы BI", section_titles)
        merged_labels = [item.get("label") for slide in plan if slide.get("kind") == "content" for item in (slide.get("items") or []) if item.get("kind") == "label"]
        self.assertIn("Зачем нужно BI", merged_labels)
        self.assertTrue(source.get("suppress_overview"))
        self.assertTrue(source.get("suppress_title_preview"))
        self.assertFalse(any(item.get("kind") == "overview" for item in plan))
        title_items = [item for item in plan if item.get("kind") == "title"]
        self.assertEqual(len(title_items), 1)
        self.assertEqual(title_items[0].get("preview_titles"), [])

    def test_build_presentation_plan_keeps_short_bi_sections_on_single_slide(self):
        text = (
            "Слайд 1: Определение BI\n"
            "- источники данных\n"
            "- слой интеграции\n"
            "- слой хранения\n"
            "- семантический слой\n"
            "- слой аналитики\n"
            "- слой визуализации\n"
        )
        source = self.backend.extract_presentation_source_from_thread(text, "BI")
        plan = self.backend.build_presentation_plan(source)
        content_titles = [item.get("title") for item in plan if item.get("kind") == "content"]

        self.assertEqual(content_titles, ["Определение BI"])

    def test_build_presentation_plan_merges_adjacent_short_sections_when_previous_slide_has_space(self):
        text = (
            "Слайд 1: Контекст ITFM\n"
            "- рост затрат\n"
            "- слабая прозрачность\n"
            "\n"
            "Слайд 2: Быстрые эффекты\n"
            "- единая модель затрат\n"
            "- общий словарь метрик\n"
        )
        source = self.backend.extract_presentation_source_from_thread(text, "ITFM")
        plan = self.backend.build_presentation_plan(source)
        content_items = [item for item in plan if item.get("kind") == "content"]

        self.assertEqual(len(content_items), 1)
        self.assertEqual(content_items[0].get("title"), "Контекст ITFM")
        labels = [item.get("label") for item in content_items[0].get("items", []) if item.get("kind") == "label"]
        self.assertIn("Быстрые эффекты", labels)

    def test_build_presentation_plan_does_not_duplicate_cover_and_overview_for_explicit_slide_outline(self):
        text = (
            "Слайд 1: Титульный\n"
            "Тема презентации: IT Financial Management (ITFM)\n"
            "Подзаголовок: Обзор, зачем нужно, как внедрять\n\n"
            "Слайд 2: Что такое IT Financial Management?\n"
            "- дисциплина планирования и контроля затрат\n"
            "- согласование ИТ-расходов с бизнес-целями\n\n"
            "Слайд 3: Зачем нужно ITFM?\n"
            "- прозрачность затрат\n"
            "- оптимизация расходов\n"
        )
        source = self.backend.extract_presentation_source_from_thread(text, "ITFM")
        plan = self.backend.build_presentation_plan(source)

        self.assertTrue(source.get("explicit_slide_mode"))
        self.assertTrue(source.get("suppress_overview"))
        self.assertTrue(source.get("suppress_title_preview"))
        self.assertEqual([item.get("kind") for item in plan].count("title"), 1)
        self.assertEqual([item.get("kind") for item in plan].count("overview"), 0)
        content_titles = [item.get("title") for item in plan if item.get("kind") == "content"]
        self.assertNotIn("Титульный", content_titles)
        self.assertEqual(content_titles, ["Что такое IT Financial Management?"])
        merged_labels = [item.get("label") for slide in plan if slide.get("kind") == "content" for item in (slide.get("items") or []) if item.get("kind") == "label"]
        self.assertIn("Зачем нужно ITFM?", merged_labels)

    def test_choose_content_chunk_preferred_prefers_single_slide_for_medium_bullets(self):
        items = [
            {"kind": "bullet", "text": f"Пункт {idx}: короткое описание value stream и cost transparency", "runs": self.backend.make_runs(f"Пункт {idx}: короткое описание value stream и cost transparency")}
            for idx in range(1, 9)
        ]

        preferred = self.backend.choose_content_chunk_preferred(items)

        self.assertEqual(preferred, len(items))

    def test_choose_pptx_body_font_size_shrinks_before_splitting(self):
        items = [
            {"kind": "bullet", "text": f"Пункт {idx}: описание процесса и данных для ITFM", "runs": self.backend.make_runs(f"Пункт {idx}: описание процесса и данных для ITFM")}
            for idx in range(1, 8)
        ]

        font_size = self.backend.choose_pptx_body_font_size(items, subtitle=None)

        self.assertLess(font_size, 12)
        self.assertGreaterEqual(font_size, 10)

    def test_choose_content_chunk_preferred_keeps_sources_and_next_steps_on_single_slide(self):
        items = [
            {"kind": "bullet", "text": text, "runs": self.backend.make_runs(text)}
            for text in [
                "Использовать сервисную модель и каталог услуг как основу управленческого контура.",
                "Свести showback и chargeback к понятным правилам аллокации для CIO и CFO.",
                "Определить владельцев данных и обновить дисциплину качества финансовых и сервисных справочников.",
                "Запустить пилот на 1–2 бизнес-сервисах и затем расширять покрытие по этапам.",
                "Использовать TBM/ITFM-практики как ориентир для модели метрик и отчётности.",
                "Следующим шагом согласовать scope, пилот и критерии управленческой полезности.",
            ]
        ]

        preferred = self.backend.choose_content_chunk_preferred(items, "summary")

        self.assertEqual(preferred, len(items))

    def test_choose_content_chunk_preferred_relaxes_roadmap_for_medium_step_plan(self):
        items = [
            {"kind": "numbered", "text": text, "runs": self.backend.make_runs(text)}
            for text in [
                "Диагностика текущей модели затрат и структуры сервисов.",
                "Определение сервисной модели и драйверов аллокации.",
                "Настройка showback и первого управленческого отчёта.",
                "Пилот на ограниченном наборе сервисов и валидация качества данных.",
                "Расширение покрытия и переход к регулярному review с бизнесом.",
            ]
        ]

        preferred = self.backend.choose_content_chunk_preferred(items, "roadmap")

        self.assertEqual(preferred, len(items))

    def test_parse_equals_slide_markers_as_headings_for_pptx_export(self):
        text = (
            "=== Слайд 1: Титульный ===\n"
            "Тема презентации: BI\n\n"
            "=== Слайд 2: Определение BI ===\n"
            "- источники данных\n"
            "- слой интеграции\n"
        )
        source = self.backend.extract_presentation_source_from_thread(text, "BI")
        plan = self.backend.build_presentation_plan(source)
        content_titles = [item.get("title") for item in plan if item.get("kind") == "content"]

        self.assertIn("Титульный", content_titles)
        self.assertIn("Определение BI", content_titles)

    def test_presentation_enhancement_followup_uses_focused_context_and_skips_collection_route(self):
        with self.backend.db_connect() as conn:
            existing = conn.execute("SELECT id FROM users WHERE email = ?", ("victoria-presentation-followup@demo.local",)).fetchone()
        user_id = int(existing["id"]) if existing else self.create_user("victoria-presentation-followup@demo.local")
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "BI presentation followup",
            [
                ("user", "Подготовь материал по BI в разбивке по слайдам", {"user_text": "Подготовь материал по BI в разбивке по слайдам"}),
                ("assistant", "Слайд 1: Титульный\nТема: BI\n\nСлайд 2: Определение BI\n- BI — это ...\n\nСлайд 3: Архитектура\n- Источники\n- ETL\n- Хранилище", {"message_kind": "chat_response"}),
                ("user", "Добавь разметки и форматирования. И, если где-то можно, то картинок или ссылок из интернета.", {"user_text": "Добавь разметки и форматирования. И, если где-то можно, то картинок или ссылок из интернета."}),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
            profile = self.backend.user_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone(), conn)

        self.assertTrue(self.backend.is_presentation_enhancement_followup(rows[-1]["content"]))
        self.assertTrue(self.backend.should_use_focused_followup_context(rows, {}))
        prompt = self.backend.build_focused_followup_messages(rows, profile, "BI presentation followup", {})[-1]["content"].lower()
        self.assertIn("весь материал целиком", prompt)
        self.assertIn("не выдумывай url", prompt)

    def test_process_chat_task_prefers_llm_over_collection_for_presentation_enhancement_followup(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "BI presentation process",
            [
                ("user", "Подготовь материал по BI в разбивке по слайдам", {"user_text": "Подготовь материал по BI в разбивке по слайдам"}),
                ("assistant", "Слайд 1: Титульный\nТема: BI\n\nСлайд 2: Определение BI\n- BI — это ...\n\nСлайд 3: Архитектура\n- Источники\n- ETL\n- Хранилище", {"message_kind": "chat_response"}),
                ("user", "Добавь разметки и форматирования. И, если где-то можно, то картинок или ссылок из интернета.", {"user_text": "Добавь разметки и форматирования. И, если где-то можно, то картинок или ссылок из интернета."}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[2], message_ids[3], '{}', ts),
            )
            task_id = int(cur.fetchone()[0])

        original_collection = self.backend.build_collection_clarification_or_contract_reply
        original_call = self.backend.call_hermes_messages
        calls = []
        try:
            def fake_collection(*args, **kwargs):
                raise AssertionError("presentation enhancement followup should not go to collection clarification")

            def fake_call(messages, model_name=None):
                calls.append(messages)
                return ("**Слайд 1: Титульный**\n- BI\n\n**Слайд 2: Определение BI**\n- BI — это ...", {"model": model_name or "fake"})

            self.backend.build_collection_clarification_or_contract_reply = fake_collection
            self.backend.call_hermes_messages = fake_call
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.build_collection_clarification_or_contract_reply = original_collection
            self.backend.call_hermes_messages = original_call

        self.assertTrue(calls)
        joined = "\n".join(item.get("content", "") for item in calls[0]).lower()
        self.assertIn("весь материал целиком", joined)
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content FROM messages WHERE id = ?', (message_ids[3],)).fetchone()
        self.assertIn("слайд 1", row['content'].lower())

    def test_build_generated_file_messages_uses_source_context_and_forces_russian(self):
        user_id = self.create_user("victoria-generated-file@demo.local")
        thread_id, _ = self.create_thread_with_messages(
            user_id,
            "ITFM generated file",
            [
                ("user", "Сделай презентацию в pptx по итогам обсуждения ITFM: проблема, целевая архитектура, этапы внедрения, риски и рекомендации", {"user_text": "Сделай презентацию в pptx по итогам обсуждения ITFM: проблема, целевая архитектура, этапы внедрения, риски и рекомендации"}),
                ("assistant", "Суть обсуждения: ITFM нужен как управленческий слой между финансами и ИТ. Основные проблемы — непрозрачная стоимость сервисов, слабая аллокация затрат и отсутствие единой модели сервиса. Рекомендуемая логика — сервисная модель, showback/chargeback, каталог услуг, поэтапное внедрение и контроль рисков данных и организационного сопротивления.", {"message_kind": "chat_response"}),
                ("user", "В формате документа", {"user_text": "В формате документа"}),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
            profile = self.backend.user_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone(), conn)

        restored = self.backend.infer_generated_file_followup_request_text(rows, rows[-1]["id"], "В формате документа")
        messages = self.backend.build_generated_file_messages(rows, profile, "ITFM generated file", restored)
        prompt = messages[-1]["content"].lower()
        self.assertIn("пиши строго на русском языке", prompt)
        self.assertIn("опорный содержательный материал из диалога", prompt)
        self.assertIn("сервисная модель", prompt)
        self.assertIn("itfm", prompt)
        self.assertIn("в формате документа", prompt)

    def test_process_chat_task_routes_generated_file_followup_with_restored_source_request(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "ITFM process route",
            [
                ("user", "Сделай презентацию в pptx по итогам обсуждения ITFM: проблема, целевая архитектура, этапы внедрения, риски и рекомендации", {"user_text": "Сделай презентацию в pptx по итогам обсуждения ITFM: проблема, целевая архитектура, этапы внедрения, риски и рекомендации"}),
                ("assistant", "Текст по слайдам подготовлен", {"message_kind": "chat_response"}),
                ("user", "По слайдам", {"user_text": "По слайдам"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[2], message_ids[3], '{}', ts),
            )
            task_id = int(cur.fetchone()[0])

        original = self.backend.call_generated_file_content
        original_build_reply = self.backend.build_generated_file_reply
        captured = {}
        try:
            def fake_call(message_rows, profile, thread_title, user_text, request_policy=None):
                captured['user_text'] = user_text
                return ('Слайд 1. Контекст\n- ITFM как управленческий слой', {'model': 'fake'})
            def fake_build_reply(**kwargs):
                return (
                    'Готово. Собрала новый ответ в файле PPTX.',
                    {'message_kind': 'file_response', 'export_format': 'pptx', 'files': [{'name': 'itfm.pptx', 'path': '/tmp/itfm.pptx', 'size_bytes': 10}]},
                )
            self.backend.call_generated_file_content = fake_call
            self.backend.build_generated_file_reply = fake_build_reply
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.call_generated_file_content = original
            self.backend.build_generated_file_reply = original_build_reply

        self.assertIn('itfm', captured.get('user_text', '').lower())
        self.assertIn('pptx', captured.get('user_text', '').lower())
        self.assertIn('по слайдам', captured.get('user_text', '').lower())
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT meta_json FROM messages WHERE id = ?', (message_ids[3],)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['export_format'], 'pptx')

    def test_build_generated_file_messages_prefers_first_four_discussion_messages_for_itfm_slide_rebuild(self):
        user_id = self.create_user("victoria-itfm-focus@demo.local")
        thread_id, _ = self.create_thread_with_messages(
            user_id,
            "ITFM deep dive",
            [
                ("user", "Разберём ITFM: где сейчас главная управленческая проблема?", {"user_text": "Разберём ITFM: где сейчас главная управленческая проблема?"}),
                ("assistant", "Главная проблема — ИТ-расходы видны как бюджетные статьи, но не как стоимость сервисов и решений для бизнеса.", {"message_kind": "chat_response"}),
                ("user", "Что должно быть в целевом контуре?", {"user_text": "Что должно быть в целевом контуре?"}),
                ("assistant", "Нужны сервисная модель, драйверы аллокации, правила showback и управленческая отчётность для CIO и CFO.", {"message_kind": "chat_response"}),
                ("user", "Сделай презентацию в pptx по итогам обсуждения ITFM", {"user_text": "Сделай презентацию в pptx по итогам обсуждения ITFM"}),
                ("assistant", "Текст по слайдам подготовлен", {"message_kind": "chat_response"}),
                ("user", "По слайдам", {"user_text": "По слайдам"}),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
            profile = self.backend.user_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone(), conn)

        restored = self.backend.infer_generated_file_followup_request_text(rows, rows[-1]["id"], "По слайдам")
        messages = self.backend.build_generated_file_messages(rows, profile, "ITFM deep dive", restored)
        self.assertEqual(len(messages), 2)
        prompt = messages[-1]["content"].lower()
        self.assertIn("ключевой фрагмент исходного обсуждения", prompt)
        self.assertIn("1. пользователь: разберём itfm", prompt)
        self.assertIn("2. ассистент: главная проблема", prompt)
        self.assertIn("3. пользователь: что должно быть в целевом контуре", prompt)
        self.assertIn("4. ассистент: нужны сервисная модель", prompt)
        self.assertNotIn("текст по слайдам подготовлен", prompt)
        self.assertNotIn("сделай презентацию в pptx по итогам обсуждения itfm", prompt)

    def test_build_generated_file_messages_does_not_apply_itfm_focus_to_non_itfm_threads(self):
        user_id = self.create_user("victoria-non-itfm-focus@demo.local")
        thread_id, _ = self.create_thread_with_messages(
            user_id,
            "ERP budgeting deep dive",
            [
                ("user", "Разберём ERP-бюджетирование: где главная проблема?", {"user_text": "Разберём ERP-бюджетирование: где главная проблема?"}),
                ("assistant", "Главная проблема — разрыв между бюджетным циклом и дорожной картой внедрения.", {"message_kind": "chat_response"}),
                ("user", "Что должно быть в целевом контуре?", {"user_text": "Что должно быть в целевом контуре?"}),
                ("assistant", "Нужны единая модель планирования, финансовые контроли и проектная отчётность.", {"message_kind": "chat_response"}),
                ("user", "Сделай презентацию в pptx по итогам обсуждения", {"user_text": "Сделай презентацию в pptx по итогам обсуждения"}),
                ("assistant", "Текст по слайдам подготовлен", {"message_kind": "chat_response"}),
                ("user", "По слайдам", {"user_text": "По слайдам"}),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
            profile = self.backend.user_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone(), conn)

        restored = self.backend.infer_generated_file_followup_request_text(rows, rows[-1]["id"], "По слайдам")
        messages = self.backend.build_generated_file_messages(rows, profile, "ERP budgeting deep dive", restored)
        self.assertGreater(len(messages), 2)
        prompt = messages[-1]["content"].lower()
        self.assertNotIn("ключевой фрагмент исходного обсуждения", prompt)
        self.assertIn("текст по слайдам подготовлен", prompt)

    def test_build_generated_file_reply_creates_pptx_attachment(self):
        if self.backend.load_pptx_module() is None:
            self.skipTest("python-pptx is not installed in this test environment")
        public_text, meta = self.backend.build_generated_file_reply(
            assistant_message_id=123,
            reply_text="Slide 1: Заголовок\n- пункт",
            reply_meta={"message_kind": "chat_response"},
            thread_title="PPTX output",
            export_format="pptx",
            created_at="2026-06-25T19:00:00+00:00",
        )
        self.assertIn("Собрала новый ответ", public_text)
        self.assertEqual(meta["message_kind"], "file_response")
        self.assertEqual(meta["export_format"], "pptx")
        self.assertEqual(meta["attachments"][0]["mime_type"], "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        self.assertTrue(meta["attachments"][0]["original_name"].endswith(".pptx"))


    def test_build_generated_file_reply_docx_strips_limitation_prelude_and_keeps_word_structure(self):
        if self.backend.load_docx_module() is None:
            self.skipTest("python-docx is not installed in this test environment")
        reply_text, meta = self.backend.build_generated_file_reply(
            assistant_message_id=778,
            reply_text=(
                "Я не могу напрямую создать бинарный файл .pptx, поэтому ниже даю содержимое в формате Markdown.\n\n"
                "**Слайд 1 – Титульный**\n"
                "**Заголовок:** ITFM\n"
                "**Подзаголовок:** Виктория • 25 июня 2026\n\n"
                "**Слайд 2 – Что такое IT Financial Management?**\n"
                "- Управление затратами и прозрачностью ИТ\n"
                "- Связь ИТ-услуг с финансовой моделью бизнеса\n\n"
                "**Слайд 3 – Роли**\n"
                "| Роль | Зона ответственности |\n"
                "| --- | --- |\n"
                "| CIO | Спонсор |\n"
                "| Архитектор | Целевой контур |\n\n"
                "Вы можете создать новую презентацию, добавить слайды с указанными заголовками и скопировать соответствующие bullet-points.\n"
                "При необходимости я могу помочь уточнить детали."
            ),
            reply_meta={"message_kind": "chat_response"},
            thread_title="Victoria ITFM",
            export_format="docx",
            created_at="2026-06-25T00:00:00+00:00",
        )
        self.assertIn('.docx', reply_text)
        local_path = meta["attachments"][0]["local_path"]
        document = self.backend.load_docx_module().Document(local_path)
        paragraph_text = "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()).replace("\xa0", " ").replace("\t", " ")
        table_text = "\n".join(cell.text.strip() for table in document.tables for row in table.rows for cell in row.cells if cell.text.strip()).replace("\xa0", " ").replace("\t", " ")
        full_text = "\n".join(part for part in [paragraph_text, table_text] if part)
        self.assertIn("Титульный", full_text)
        self.assertNotIn("Слайд 1 – Титульный", full_text)
        self.assertIn("Заголовок:", full_text)
        self.assertIn("ITFM", full_text)
        self.assertIn("Подзаголовок:", full_text)
        self.assertIn("Виктория • 25 июня 2026", full_text)
        self.assertNotIn("не могу напрямую создать бинарный файл", full_text.lower())
        self.assertNotIn("вы можете создать новую презентацию", full_text.lower())
        collected_runs = []
        for paragraph in document.paragraphs:
            collected_runs.extend(paragraph.runs)
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        collected_runs.extend(paragraph.runs)
        self.assertTrue(any((run.text or '').startswith('Заголовок:') and run.bold for run in collected_runs))
        styles = [paragraph.style.name for paragraph in document.paragraphs if paragraph.text.strip()]
        self.assertIn("Heading 1", styles)
        self.assertIn("List Bullet", styles)
        self.assertGreaterEqual(len(document.tables), 1)
        normal_style = document.styles['Normal']
        self.assertEqual(normal_style.font.name, 'Arial')
        self.assertEqual(getattr(normal_style.font.size, 'pt', None), 12)
        all_table_rows = [
            [cell.text.strip() for cell in row.cells]
            for table in document.tables
            for row in table.rows
        ]
        self.assertIn(["Роль", "Зона ответственности"], all_table_rows)
        self.assertIn(["CIO", "Спонсор"], all_table_rows)

    def test_build_generated_file_reply_pptx_uses_widescreen_and_structured_slides(self):
        if self.backend.load_pptx_module() is None:
            self.skipTest("python-pptx is not installed in this test environment")
        _, meta = self.backend.build_generated_file_reply(
            assistant_message_id=779,
            reply_text=(
                "Я не могу напрямую создать бинарный файл .pptx, поэтому ниже даю содержимое в формате Markdown.\n\n"
                "**Слайд 1 – Титульный**\n"
                "**Заголовок:** ITFM\n"
                "**Подзаголовок:** Виктория • 25 июня 2026\n\n"
                "**Слайд 2 – Что такое IT Financial Management?**\n"
                "- Управление затратами и прозрачностью ИТ\n"
                "- Связь ИТ-услуг с финансовой моделью бизнеса\n\n"
                "**Слайд 3 – Роли**\n"
                "| Роль | Зона ответственности |\n"
                "| --- | --- |\n"
                "| CIO | Спонсор |\n"
                "| Архитектор | Целевой контур |\n\n"
                "Вы можете создать новую презентацию, добавить слайды с указанными заголовками и скопировать соответствующие bullet-points.\n"
                "При необходимости я могу помочь уточнить детали."
            ),
            reply_meta={"message_kind": "chat_response"},
            thread_title="Victoria ITFM",
            export_format="pptx",
            created_at="2026-06-25T00:00:00+00:00",
        )
        pptx_module = self.backend.load_pptx_module()
        presentation = pptx_module.Presentation(meta["attachments"][0]["local_path"])
        inches = pptx_module.util.Inches
        self.assertEqual(presentation.slide_width, inches(13.333))
        self.assertEqual(presentation.slide_height, inches(7.5))
        self.assertGreaterEqual(len(presentation.slides), 4)
        joined_text = []
        table_count = 0
        for slide in presentation.slides:
            for shape in slide.shapes:
                text = getattr(shape, 'text', '')
                if text:
                    joined_text.append(text)
                if getattr(shape, 'has_table', False):
                    table_count += 1
        combined = "\n".join(joined_text)
        self.assertIn("ITFM", combined)
        self.assertIn("Виктория • 25 июня 2026", combined)
        self.assertIn("IT Financial Management", combined)
        self.assertIn("Структура презентации", combined)
        self.assertNotIn("Слайд 2 – Что такое IT Financial Management?", combined)
        self.assertNotIn("не могу напрямую создать бинарный файл", combined.lower())
        self.assertNotIn("вы можете создать новую презентацию", combined.lower())
        self.assertNotIn("example.com", combined.lower())
        self.assertNotIn("изображение:", combined.lower())
        self.assertNotIn("![", combined)
        self.assertNotIn("hermes web export", combined.lower())
        self.assertNotIn("generated export", combined.lower())
        self.assertGreaterEqual(table_count, 1)

    def test_presentation_source_and_plan_strip_technical_tail_and_build_typed_slides(self):
        source = self.backend.extract_presentation_source_from_thread(
            "Я не могу напрямую создать бинарный файл .pptx, поэтому ниже даю содержимое в формате Markdown.\n\n"
            "**Слайд 1 – Титульный**\n"
            "**Заголовок:** ITFM\n"
            "**Подзаголовок:** Управленческая прозрачность ИТ\n\n"
            "**Слайд 2 – Сравнение вариантов**\n"
            "**Вариант 1:** Единая сервисная модель\n"
            "**Вариант 2:** Локальные оптимизации\n"
            "**Компромисс:** Начать с пилота\n\n"
            "**Слайд 3 – План внедрения**\n"
            "1. Диагностика\n"
            "2. Целевая модель\n"
            "3. Внедрение\n\n"
            "Вы можете создать новую презентацию, добавить слайды с указанными заголовками.\n",
            "Victoria ITFM",
        )
        self.assertEqual(source["deck_title"], "ITFM")
        self.assertEqual(source["deck_subtitle"], "Управленческая прозрачность ИТ")
        self.assertEqual(source["overview_titles"], ["Сравнение вариантов", "План внедрения"])

        plan = self.backend.build_presentation_plan(source)
        kinds = [item.get("kind") for item in plan]
        self.assertEqual(kinds[:4], ["title", "overview", "comparison", "roadmap"])
        serialized = json.dumps(plan, ensure_ascii=False)
        self.assertNotIn("не могу напрямую создать бинарный файл", serialized.lower())
        self.assertNotIn("вы можете создать новую презентацию", serialized.lower())

    def test_presentation_plan_balances_long_sections_and_splits_large_overview(self):
        source = {
            "deck_title": "ITFM",
            "deck_subtitle": "Композиционный тест",
            "overview_titles": [f"Раздел {index}" for index in range(1, 9)],
            "sections": [
                {
                    "title": "Длинный раздел",
                    "items": [
                        {"kind": "bullet", "text": f"Пункт {index}", "runs": [{"text": f"Пункт {index}"}]}
                        for index in range(1, 10)
                    ],
                    "tables": [],
                },
                {
                    "title": "План внедрения",
                    "items": [
                        {"kind": "numbered", "text": f"Этап {index}", "runs": [{"text": f"Этап {index}"}]}
                        for index in range(1, 7)
                    ],
                    "tables": [],
                },
            ],
        }
        plan = self.backend.build_presentation_plan(source)
        overview_slides = [item for item in plan if item.get("kind") == "overview"]
        self.assertEqual(len(overview_slides), 2)
        self.assertEqual(len(overview_slides[0]["titles"]), 4)
        self.assertEqual(len(overview_slides[1]["titles"]), 4)

        content_slides = [item for item in plan if item.get("kind") == "content" and str(item.get("title") or "").startswith("Длинный раздел")]
        self.assertEqual([len(item.get("items") or []) for item in content_slides], [5, 4])
        self.assertTrue(any("продолжение" in str(item.get("title") or "").lower() for item in content_slides[1:]))

        roadmap_slides = [item for item in plan if item.get("kind") == "roadmap"]
        self.assertEqual([len(item.get("items") or []) for item in roadmap_slides], [3, 3])

    def test_build_generated_file_reply_pptx_uses_arial_typography_defaults(self):
        if self.backend.load_pptx_module() is None:
            self.skipTest("python-pptx is not installed in this test environment")
        _, meta = self.backend.build_generated_file_reply(
            assistant_message_id=781,
            reply_text=(
                "**Слайд 1 – Титульный**\n"
                "**Заголовок:** ITFM\n"
                "**Подзаголовок:** Управленческая прозрачность ИТ\n\n"
                "**Слайд 2 – Риски**\n"
                "**Качество данных:** Без нормализации модель затрат искажается.\n"
                "- Нужна единая сервисная модель\n"
                "- Нужны согласованные драйверы аллокации\n"
            ),
            reply_meta={"message_kind": "chat_response"},
            thread_title="Victoria ITFM",
            export_format="pptx",
            created_at="2026-06-25T00:00:00+00:00",
        )
        pptx_module = self.backend.load_pptx_module()
        presentation = pptx_module.Presentation(meta["attachments"][0]["local_path"])

        def find_runs_by_text(target: str):
            found = []
            for slide in presentation.slides:
                for shape in slide.shapes:
                    text_frame = getattr(shape, 'text_frame', None)
                    if text_frame is None:
                        continue
                    for paragraph in text_frame.paragraphs:
                        for run in paragraph.runs:
                            if (run.text or '').strip() == target:
                                found.append(run)
            return found

        title_runs = find_runs_by_text('ITFM')
        self.assertTrue(title_runs)
        self.assertTrue(any(run.font.name == 'Arial' and getattr(run.font.size, 'pt', None) == 20 for run in title_runs))

        subtitle_runs = find_runs_by_text('Управленческая прозрачность ИТ')
        self.assertTrue(subtitle_runs)
        self.assertTrue(any(run.font.name == 'Arial' and getattr(run.font.size, 'pt', None) == 14 for run in subtitle_runs))

        body_runs = find_runs_by_text('Нужна единая сервисная модель')
        self.assertTrue(body_runs)
        self.assertTrue(any(run.font.name == 'Arial' and getattr(run.font.size, 'pt', None) == 12 for run in body_runs))

    def test_build_generated_file_reply_pptx_uses_specialized_slide_types_for_comparison_roadmap_and_risks(self):
        if self.backend.load_pptx_module() is None:
            self.skipTest("python-pptx is not installed in this test environment")
        _, meta = self.backend.build_generated_file_reply(
            assistant_message_id=780,
            reply_text=(
                "**Слайд 1 – Титульный**\n"
                "**Заголовок:** ITFM target operating model\n"
                "**Подзаголовок:** Сравнение вариантов и план внедрения\n\n"
                "**Слайд 2 – Сравнение подходов**\n"
                "**Вариант A:** BI + ручная модель аллокации\n"
                "**Вариант B:** Специализированная ITFM-платформа\n"
                "**Компромисс:** Быстрый старт против глубины автоматизации\n\n"
                "**Слайд 3 – Дорожная карта внедрения**\n"
                "1. Диагностика источников затрат и сервисного каталога\n"
                "2. Пилот showback на одном бизнес-юните\n"
                "3. Масштабирование модели на всю ИТ-функцию\n\n"
                "**Слайд 4 – Ключевые риски**\n"
                "**Качество данных:** нет единой модели сервисов\n"
                "**Сопротивление:** бизнес и ИТ по-разному читают цифры\n"
                "**Мера ответа:** единые правила аллокации и governance\n"
            ),
            reply_meta={"message_kind": "chat_response"},
            thread_title="ITFM operating model",
            export_format="pptx",
            created_at="2026-06-26T00:00:00+00:00",
        )
        pptx_module = self.backend.load_pptx_module()
        presentation = pptx_module.Presentation(meta["attachments"][0]["local_path"])
        combined = "\n".join(
            getattr(shape, 'text', '')
            for slide in presentation.slides
            for shape in slide.shapes
            if getattr(shape, 'text', '')
        )
        self.assertIn("Сравнение вариантов", combined)
        self.assertIn("Поэтапный план внедрения", combined)
        self.assertIn("Риски и меры", combined)
        self.assertIn("Вариант A", combined)
        self.assertIn("Диагностика источников затрат и сервисного каталога", combined)
        self.assertIn("Качество данных", combined)
        self.assertEqual(len(presentation.slides), 5)
        slide_shape_counts = [len(slide.shapes) for slide in presentation.slides]
        self.assertGreaterEqual(slide_shape_counts[2], 8)
        self.assertGreaterEqual(slide_shape_counts[3], 10)
        self.assertGreaterEqual(slide_shape_counts[4], 10)

    def test_message_export_html_uses_cleaned_assistant_body_and_renders_markdown(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        assistant_content = (
            "Примечание: включён глубокий reasoning-режим для архитектурной/стратегической задачи. Он лимитирован и дороже обычного ответа.\n\n"
            "**Прямой ответ**\n\n"
            "| A | B |\n"
            "|---|---|\n"
            "| 1 | 2 |\n"
        )
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "KPI export",
            [("assistant", assistant_content, {})],
        )
        assistant_message_id = message_ids[0]

        html_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=html",
            headers=self.auth_headers(token),
        )
        self.assertEqual(html_response.status_code, 200)
        body = html_response.get_data(as_text=True)
        self.assertIn("<table>", body)
        self.assertIn("<strong>Прямой ответ</strong>", body)
        self.assertNotIn("|---|---|", body)
        self.assertNotIn("Примечание: включён глубокий reasoning-режим", body)

        json_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=json",
            headers=self.auth_headers(token),
        )
        self.assertEqual(json_response.status_code, 200)
        payload = json_response.get_json()
        self.assertTrue(payload["display_content"].startswith("**Прямой ответ**"))
        self.assertNotIn("Примечание: включён глубокий reasoning-режим", payload["display_content"])

    def test_message_export_recurring_uses_normalized_digest_body(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        recurring_blob = (
            "- короткую тему: we have \"тип поста\" (type of post) ...\n\n"
            "Дайджест ИТ-консалтинга за 25.06.2026\n"
            "Обработано непустых сообщений: 23; в дайджесте: 10.\n\n"
            "Короткая тема: аналитика\n"
            "Канал: Axenix_Ru\n"
            "[пост](https://t.me/Axenix_Ru/3357)\n"
        )
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Digest export",
            [("assistant", recurring_blob, {"source": "hermes_cron", "message_kind": "job_delivery"})],
        )
        assistant_message_id = message_ids[0]

        html_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=html",
            headers=self.auth_headers(token),
        )
        self.assertEqual(html_response.status_code, 200)
        body = html_response.get_data(as_text=True)
        self.assertIn("Дайджест ИТ-консалтинга за 25.06.2026", body)
        self.assertIn('<a href="https://t.me/Axenix_Ru/3357">пост</a>', body)
        self.assertNotIn('короткую тему: we have', body)

        json_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=json",
            headers=self.auth_headers(token),
        )
        self.assertEqual(json_response.status_code, 200)
        payload = json_response.get_json()
        self.assertTrue(payload["display_content"].startswith("Дайджест ИТ-консалтинга за 25.06.2026"))
        self.assertNotIn('короткую тему: we have', payload["display_content"])

        json_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=json",
            headers=self.auth_headers(token),
        )
        self.assertEqual(json_response.status_code, 200)
        self.assertIn("application/json", json_response.headers.get("Content-Type", ""))
        self.assertEqual(json_response.get_json()["message_id"], assistant_message_id)

        csv_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=csv",
            headers=self.auth_headers(token),
        )
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response.headers.get("Content-Type", ""))
        self.assertIn("thread_title,message_id,created_at,line_no,line", csv_response.get_data(as_text=True))

        xml_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=xml",
            headers=self.auth_headers(token),
        )
        self.assertEqual(xml_response.status_code, 200)
        self.assertIn("application/xml", xml_response.headers.get("Content-Type", ""))
        self.assertIn("<assistant_message", xml_response.get_data(as_text=True))

        rtf_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=rtf",
            headers=self.auth_headers(token),
        )
        self.assertEqual(rtf_response.status_code, 200)
        self.assertIn("application/rtf", rtf_response.headers.get("Content-Type", ""))
        self.assertTrue(rtf_response.get_data(as_text=True).startswith(r"{\rtf1"))

        docx_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=docx",
            headers=self.auth_headers(token),
        )
        self.assertEqual(docx_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx_response.headers.get("Content-Type", ""))
        self.assertTrue(docx_response.get_data().startswith(b"PK"))

        xlsx_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=xlsx",
            headers=self.auth_headers(token),
        )
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", xlsx_response.headers.get("Content-Type", ""))
        self.assertTrue(xlsx_response.get_data().startswith(b"PK"))

        xls_alias_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=xls",
            headers=self.auth_headers(token),
        )
        self.assertEqual(xls_alias_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", xls_alias_response.headers.get("Content-Type", ""))
        self.assertTrue(xls_alias_response.get_data().startswith(b"PK"))

        pptx_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=pptx",
            headers=self.auth_headers(token),
        )
        self.assertEqual(pptx_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.presentationml.presentation", pptx_response.headers.get("Content-Type", ""))
        self.assertTrue(pptx_response.get_data().startswith(b"PK"))

        doc_alias_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=doc",
            headers=self.auth_headers(token),
        )
        self.assertEqual(doc_alias_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.wordprocessingml.document", doc_alias_response.headers.get("Content-Type", ""))
        self.assertTrue(doc_alias_response.get_data().startswith(b"PK"))

        pdf_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=pdf",
            headers=self.auth_headers(token),
        )
        self.assertEqual(pdf_response.status_code, 200)
        self.assertIn("application/pdf", pdf_response.headers.get("Content-Type", ""))
        self.assertTrue(pdf_response.get_data().startswith(b"%PDF"))

        py_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=py",
            headers=self.auth_headers(token),
        )
        self.assertEqual(py_response.status_code, 200)
        self.assertIn("text/x-python", py_response.headers.get("Content-Type", ""))
        self.assertIn("CONTENT =", py_response.get_data(as_text=True))

        png_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=png",
            headers=self.auth_headers(token),
        )
        self.assertEqual(png_response.status_code, 200)
        self.assertIn("image/png", png_response.headers.get("Content-Type", ""))
        self.assertTrue(png_response.get_data().startswith(b"\x89PNG"))

        jpeg_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=jpeg",
            headers=self.auth_headers(token),
        )
        self.assertEqual(jpeg_response.status_code, 200)
        self.assertIn("image/jpeg", jpeg_response.headers.get("Content-Type", ""))
        self.assertTrue(jpeg_response.get_data().startswith(b"\xff\xd8\xff"))

        unsupported = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=epub",
            headers=self.auth_headers(token),
        )
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(unsupported.get_json()["error"], "unsupported_export_format")

    def test_build_generated_file_reply_allows_csv(self):
        reply_text, meta = self.backend.build_generated_file_reply(
            assistant_message_id=123,
            reply_text="col1,col2\n1,2\n",
            reply_meta={"message_kind": "chat_response"},
            thread_title="Digest",
            export_format="csv",
            created_at="2026-06-25T00:00:00+00:00",
        )
        self.assertIn('.csv', reply_text)
        attachments = meta.get("attachments") or []
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get("mime_type"), "text/csv; charset=utf-8")
        self.assertEqual(meta.get("export_format"), "csv")
        self.assertTrue(meta.get("generated_from_request"))

    def test_build_generated_file_reply_docx_omits_technical_metadata_and_keeps_structure(self):
        if self.backend.load_docx_module() is None:
            self.skipTest("python-docx is not installed in this test environment")
        reply_text, meta = self.backend.build_generated_file_reply(
            assistant_message_id=777,
            reply_text="# ITFM roadmap\n\nКраткое резюме для руководителя.\n\n## Этапы\n- Диагностика\n- Целевая архитектура\n\n## Роли\n| Роль | Зона ответственности |\n| --- | --- |\n| CIO | Спонсор |\n| Архитектор | Целевой контур |\n",
            reply_meta={"message_kind": "chat_response"},
            thread_title="Victoria ITFM",
            export_format="docx",
            created_at="2026-06-25T00:00:00+00:00",
        )
        self.assertIn('.docx', reply_text)
        attachments = meta.get("attachments") or []
        self.assertEqual(len(attachments), 1)
        local_path = attachments[0].get("local_path")
        self.assertTrue(local_path and os.path.exists(local_path))

        docx_module = self.backend.load_docx_module()
        document = docx_module.Document(local_path)
        paragraph_texts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        full_text = "\n".join(paragraph_texts)
        self.assertIn("ITFM roadmap", full_text)
        self.assertIn("Краткое резюме для руководителя.", full_text)
        self.assertIn("Этапы", full_text)
        self.assertIn("Диагностика", full_text)
        self.assertIn("Целевая архитектура", full_text)
        self.assertNotIn("Чат:", full_text)
        self.assertNotIn("Сообщение #", full_text)
        self.assertNotIn("Дата:", full_text)

        styles = [paragraph.style.name for paragraph in document.paragraphs if paragraph.text.strip()]
        self.assertIn("Heading 1", styles)
        self.assertIn("Heading 2", styles)
        self.assertIn("List Bullet", styles)
        self.assertEqual(len(document.tables), 1)
        table_rows = [[cell.text for cell in row.cells] for row in document.tables[0].rows]
        self.assertEqual(table_rows[0][:2], ["Роль", "Зона ответственности"])
        self.assertEqual(table_rows[1][:2], ["CIO", "Спонсор"])

    def test_message_export_docx_omits_technical_metadata(self):
        if self.backend.load_docx_module() is None:
            self.skipTest("python-docx is not installed in this test environment")
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Victoria ITFM export",
            [
                ("user", "Сделай summary", {}),
                ("assistant", "# Итоги\n\nСогласованный план.\n\n- Шаг 1\n- Шаг 2", {"message_kind": "chat_response"}),
            ],
        )
        assistant_message_id = message_ids[-1]
        token = self.login()

        docx_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=docx",
            headers=self.auth_headers(token),
        )
        self.assertEqual(docx_response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx_response.headers.get("Content-Type", ""))
        document = self.backend.load_docx_module().Document(io.BytesIO(docx_response.get_data()))
        exported_text = "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
        self.assertIn("Итоги", exported_text)
        self.assertIn("Согласованный план.", exported_text)
        self.assertIn("Шаг 1", exported_text)
        self.assertNotIn("Чат:", exported_text)
        self.assertNotIn("Сообщение #", exported_text)
        self.assertNotIn("Дата:", exported_text)


    def test_personalization_uses_user_profile_without_default_agent_name(self):
        token = self.login(email="misha@demo.local", password="12345678") if self.client.post("/api/auth/login", json={"email": "misha@demo.local", "password": "12345678"}).status_code == 200 else self.login()
        response = self.client.patch(
            "/api/me",
            headers=self.auth_headers(token),
            json={
                "goals": "Держать фокус на multi-user web runtime.",
                "constraints": "Без файловой персонализации.",
                "assistant_profile": {
                    "tone": "business",
                    "answer_depth": "detailed",
                    "interaction_mode": "compare_options",
                    "about_user": "Работает через frontend с несколькими users.",
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        personalization = response.get_json()["personalization"]
        self.assertIn("user_name=", personalization)
        self.assertIn("about_user=Работает через frontend с несколькими users.", personalization)
        self.assertNotIn("; name=", personalization)
        self.assertNotIn("\nname=", personalization)

        with self.backend.db_connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
            profile = self.backend.user_to_dict(row, conn)
        system_prompt = self.backend.build_hermes_system_prompt(profile, "Проверка")
        job_prompt = self.backend.build_job_system_prompt(profile)
        self.assertNotIn("Ты — Ева", system_prompt)
        self.assertNotIn("Ты — Ева", job_prompt)
        self.assertIn("Перед финализацией ответа сделай внутреннюю самопроверку", system_prompt)
        self.assertIn("Никогда не заявляй, что файл, документ, ссылка на скачивание или вложение уже подготовлены", system_prompt)
        self.assertIn("Hermes Web", system_prompt)

    def test_periodic_interaction_memory_writeback_saves_user_preferences_separately(self):
        user_id = self.create_user("memory-user@example.com")
        self.create_thread_with_messages(
            user_id,
            "Память",
            [
                ("user", "По умолчанию отвечай кратко. Не используй английские слова без необходимости.", {}),
                ("assistant", "Приняла. Буду отвечать кратко и без лишнего английского.", {"personalization_used": True}),
            ],
        )
        with self.backend.db_connect() as conn:
            max_message_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0])
            conn.execute("UPDATE users SET memory_last_processed_message_id = ? WHERE id <> ?", (max_message_id, user_id))

        processed = self.backend.process_interaction_memory_writeback_once(max_users=1)
        self.assertIn(processed, (0, 1))

        with self.backend.db_connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            profile = self.backend.user_to_dict(row, conn)

        self.assertEqual(profile["pinned"], [])
        self.assertTrue(profile["interaction_memory"])
        joined = " ".join(profile["interaction_memory"])
        self.assertIn("По умолчанию отвечай кратко", joined)
        self.assertIn("interaction_memory=", self.backend.build_personalization_block(profile))

    def test_periodic_interaction_memory_writeback_advances_cursor_without_duplicates(self):
        user_id = self.create_user("memory-cursor@example.com")
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Память 2",
            [
                ("user", "По умолчанию лучше сначала давать короткий вывод.", {}),
                ("assistant", "Приняла, сначала буду давать короткий вывод.", {"personalization_used": True}),
            ],
        )
        with self.backend.db_connect() as conn:
            max_message_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0])
            conn.execute("UPDATE users SET memory_last_processed_message_id = ? WHERE id <> ?", (max_message_id, user_id))

        first = self.backend.process_interaction_memory_writeback_once(max_users=1)
        second = self.backend.process_interaction_memory_writeback_once(max_users=1)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)

        with self.backend.db_connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            profile = self.backend.user_to_dict(row, conn)

        self.assertEqual(profile["memory_last_processed_message_id"], message_ids[-1])
        self.assertEqual(len(profile["interaction_memory"]), 1)

    def test_password_min_length_is_8(self):
        token = self.login()
        short_change = self.client.post(
            "/api/me/change-password",
            headers=self.auth_headers(token),
            json={"current_password": "demo123", "new_password": "1234567"},
        )
        self.assertEqual(short_change.status_code, 400)
        self.assertEqual(short_change.get_json()["error"], "password_too_short")

        valid_change = self.client.post(
            "/api/me/change-password",
            headers=self.auth_headers(token),
            json={"current_password": "demo123", "new_password": "12345678"},
        )
        self.assertEqual(valid_change.status_code, 200)

        login_new_password = self.client.post("/api/auth/login", json={"email": "misha@demo.local", "password": "12345678"})
        self.assertEqual(login_new_password.status_code, 200)

        admin_token = self.login(email="admin@demo.local", password="demo123")
        create_user = self.client.post(
            "/api/admin/users",
            headers=self.auth_headers(admin_token),
            json={"email": "minpass@example.com", "password": "12345678", "name": "Min Pass", "role": "user", "status": "active"},
        )
        self.assertIn(create_user.status_code, (200, 201))

    def test_job_display_name_and_fixed_user_recipient(self):
        admin_token = self.login(email="admin@demo.local", password="demo123")
        recipient_user_id = self.create_user("recipient@example.com")
        created_job = self.client.post(
            "/api/jobs",
            headers=self.auth_headers(admin_token),
            json={
                "name": "digest-job",
                "display_name": "Ежедневный дайджест",
                "description": "Отправка дайджеста",
                "job_type": "custom",
                "visibility": "shared",
                "status": "active",
                "schedule_kind": "daily",
                "time_of_day": "10:00",
                "timezone": "Europe/Moscow",
                "start_date": "2026-06-14",
                "parameters": {"goal": "Собрать дайджест", "context": "Тест"},
                "recipients": [
                    {"recipient_type": "owner", "target_value": "self", "label": "Владелец"},
                    {"recipient_type": "fixed_user", "target_value": str(recipient_user_id), "label": "Получатель"},
                ],
            },
        )
        self.assertEqual(created_job.status_code, 201)
        job = created_job.get_json()["job"]
        self.assertEqual(job["display_name"], "Ежедневный дайджест")
        self.assertTrue(any(item["recipient_type"] == "fixed_user" and str(item["target_value"]) == str(recipient_user_id) for item in job["recipients"]))

        with self.backend.db_connect() as conn:
            recipient_thread = conn.execute(
                "SELECT title, user_id FROM threads WHERE job_id = ? AND user_id = ? ORDER BY id ASC LIMIT 1",
                (job["id"], recipient_user_id),
            ).fetchone()
        self.assertIsNotNone(recipient_thread)
        self.assertEqual(recipient_thread["title"], "Ежедневный дайджест")

    def test_fixed_user_recipient_can_see_assigned_job_in_jobs_list(self):
        owner_token = self.login()
        recipient_email = "victoria@example.com"
        recipient_user_id = self.create_user(recipient_email)

        created_job = self.client.post(
            "/api/jobs",
            headers=self.auth_headers(owner_token),
            json={
                "name": "Weekly media watch",
                "description": "Еженедельный сбор публикаций из СМИ",
                "job_type": "research_watch",
                "visibility": "shared",
                "status": "active",
                "schedule_kind": "weekly",
                "days_of_week": ["mon"],
                "time_of_day": "09:00",
                "timezone": "Europe/Moscow",
                "start_date": "2026-06-15",
                "parameters": {"subject": "СМИ", "angle": "сбор публикаций", "output": "короткий weekly digest"},
                "recipients": [
                    {"recipient_type": "owner", "target_value": "self", "label": "Автор"},
                    {"recipient_type": "fixed_user", "target_value": str(recipient_user_id), "label": "Виктория"},
                ],
            },
        )
        self.assertEqual(created_job.status_code, 201)
        job_id = created_job.get_json()["job"]["id"]

        recipient_token = self.login(recipient_email)
        recipient_jobs = self.client.get("/api/jobs", headers=self.auth_headers(recipient_token))
        self.assertEqual(recipient_jobs.status_code, 200)
        recipient_job = next((item for item in recipient_jobs.get_json()["jobs"] if item["id"] == job_id), None)
        self.assertIsNotNone(recipient_job)
        self.assertEqual(recipient_job["role"], "recipient")

        recipient_detail = self.client.get(f"/api/jobs/{job_id}", headers=self.auth_headers(recipient_token))
        self.assertEqual(recipient_detail.status_code, 200)
        self.assertEqual(recipient_detail.get_json()["job"]["role"], "recipient")

    def test_job_timezone_defaults_to_moscow_when_owner_timezone_missing(self):
        token = self.login()
        with self.backend.db_connect() as conn:
            conn.execute("UPDATE users SET timezone = '' WHERE id = 1")

        created_job = self.client.post(
            "/api/jobs",
            headers=self.auth_headers(token),
            json={
                "name": "Moscow default timezone",
                "description": "Проверка fallback timezone",
                "job_type": "custom",
                "visibility": "private",
                "status": "active",
                "schedule_kind": "weekly",
                "days_of_week": ["mon"],
                "time_of_day": "09:00",
                "start_date": "2026-06-15",
                "parameters": {"goal": "Проверить timezone fallback", "context": "тест"},
                "recipients": [{"recipient_type": "owner", "target_value": "self", "label": "Только владелец"}],
            },
        )
        self.assertEqual(created_job.status_code, 201)
        job = created_job.get_json()["job"]
        self.assertEqual(job["timezone"], "Europe/Moscow")
        self.assertIn("09:00", job["schedule_summary"])
        self.assertIn("Europe/Moscow", job["schedule_summary"])

    def test_chat_recurring_request_creates_real_job(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Мониторинг Астры",
            [
                ("user", "Собери информацию из СМИ по упоминанию Астра Линукса", {"user_text": "Собери информацию из СМИ по упоминанию Астра Линукса"}),
                ("assistant", "Подготовила обзор по теме.", {}),
                ("user", "Можешь поставить сбор этой информации на еженедельной основе?", {"user_text": "Можешь поставить сбор этой информации на еженедельной основе?"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        user_message_id = message_ids[2]
        assistant_message_id = message_ids[3]
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, user_message_id, assistant_message_id, "{}", ts),
            )
            task_id = int(cur.fetchone()[0])

        processed = self.backend.process_chat_task(task_id)
        self.assertTrue(processed)

        with self.backend.db_connect() as conn:
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
            jobs = conn.execute("SELECT name, timezone, schedule_kind, time_of_day, days_of_week_json FROM jobs WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()

        self.assertIn("Создала задачу", assistant["content"])
        self.assertTrue(jobs)
        latest = jobs[0]
        self.assertIn("Астра Линукса", latest["name"])
        self.assertEqual(latest["timezone"], "Europe/Moscow")
        self.assertEqual(latest["schedule_kind"], "weekly")
        self.assertEqual(latest["time_of_day"], "09:00")
        self.assertEqual(json.loads(latest["days_of_week_json"]), ["mon"])

    def test_chat_recurring_request_uses_explicit_subject_from_current_message(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Мониторинг LegalAI",
            [
                ("user", "Поставь еженедельный мониторинг источников в интернете по теме LegalAI", {"user_text": "Поставь еженедельный мониторинг источников в интернете по теме LegalAI"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[0], message_ids[1], "{}", ts),
            )
            task_id = int(cur.fetchone()[0])

        self.assertTrue(self.backend.process_chat_task(task_id))

        with self.backend.db_connect() as conn:
            latest = conn.execute(
                "SELECT name, description FROM jobs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (message_ids[1],)).fetchone()

        self.assertIn("LegalAI", latest["name"])
        self.assertIn("LegalAI", latest["description"])
        self.assertIn("LegalAI", assistant["content"])

    def test_chat_recurring_request_reuses_existing_job_in_another_thread(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute(
                "SELECT id, email, role FROM users WHERE email IN (?, ?) ORDER BY CASE WHEN email = ? THEN 0 ELSE 1 END LIMIT 1",
                ("misha@demo.local", "admin@demo.local", "misha@demo.local"),
            ).fetchone()
            auth = self.backend.AuthUser(id=int(user_row["id"]), role=user_row["role"], email=user_row["email"])
            existing = self.backend.create_or_update_job(
                conn,
                auth,
                {
                    "name": "Мониторинг: Собери информацию из СМИ по упоминанию Астра Линукса",
                    "description": "Регулярный мониторинг по запросу из чата",
                    "job_type": "research_watch",
                    "visibility": "private",
                    "status": "active",
                    "schedule_kind": "weekly",
                    "days_of_week": ["mon"],
                    "time_of_day": "09:00",
                    "timezone": "Europe/Moscow",
                    "start_date": self.backend.now_utc().astimezone(self.backend.ZoneInfo("Europe/Moscow")).date().isoformat(),
                    "prompt_template": self.backend.build_default_job_template("research_watch"),
                    "parameters": {
                        "subject": "Собери информацию из СМИ по упоминанию Астра Линукса",
                        "angle": "упоминания в СМИ, значимые события, сигналы рынка и изменения позиции",
                        "output": "структурированная краткая сводка без лишней воды",
                    },
                    "recipients": [{"recipient_type": "owner", "target_value": "self", "label": "Только владелец"}],
                },
            )
        user_id = int(user_row["id"])
        second_thread_id, second_message_ids = self.create_thread_with_messages(
            user_id,
            "Мониторинг Астры 2",
            [
                ("user", "Собери информацию из СМИ по упоминанию Астра Линукса", {"user_text": "Собери информацию из СМИ по упоминанию Астра Линукса"}),
                ("assistant", "Подготовила обзор по теме.", {}),
                ("user", "Можешь поставить сбор этой информации на еженедельной основе?", {"user_text": "Можешь поставить сбор этой информации на еженедельной основе?"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )

        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            before_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? AND job_type = 'research_watch' AND name = ?",
                    (user_id, "Мониторинг: Собери информацию из СМИ по упоминанию Астра Линукса"),
                ).fetchone()["c"]
            )
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (second_thread_id, user_id, second_message_ids[2], second_message_ids[3], "{}", ts),
            )
            second_task_id = int(cur.fetchone()[0])

        self.assertTrue(self.backend.process_chat_task(second_task_id))

        with self.backend.db_connect() as conn:
            after_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? AND job_type = 'research_watch' AND name = ?",
                    (user_id, "Мониторинг: Собери информацию из СМИ по упоминанию Астра Линукса"),
                ).fetchone()["c"]
            )
            jobs = conn.execute(
                "SELECT id, name FROM jobs WHERE user_id = ? AND job_type = 'research_watch' AND name = ? ORDER BY id ASC",
                (user_id, "Мониторинг: Собери информацию из СМИ по упоминанию Астра Линукса"),
            ).fetchall()
            second_assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (second_message_ids[3],)).fetchone()

        self.assertEqual(after_count, before_count)
        self.assertIn(existing["id"], [row["id"] for row in jobs])
        self.assertIn("Такая задача уже есть", second_assistant["content"])
        second_meta = json.loads(second_assistant["meta_json"] or "{}")
        self.assertEqual(second_meta.get("message_kind"), "job_reused")
        self.assertIn(second_meta.get("created_job_id"), [row["id"] for row in jobs])

    def test_chat_run_now_request_triggers_existing_job_instead_of_creating_duplicate(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute(
                "SELECT id, email, role FROM users WHERE email IN (?, ?) ORDER BY CASE WHEN email = ? THEN 0 ELSE 1 END LIMIT 1",
                ("misha@demo.local", "admin@demo.local", "misha@demo.local"),
            ).fetchone()
            auth = self.backend.AuthUser(id=int(user_row["id"]), role=user_row["role"], email=user_row["email"])
            existing = self.backend.create_or_update_job(
                conn,
                auth,
                {
                    "name": "Мониторинг: Собери информацию из СМИ по HR-трендам",
                    "description": "Регулярный мониторинг по запросу из чата",
                    "job_type": "research_watch",
                    "visibility": "private",
                    "status": "active",
                    "schedule_kind": "weekly",
                    "days_of_week": ["mon"],
                    "time_of_day": "09:00",
                    "timezone": "Europe/Moscow",
                    "start_date": self.backend.now_utc().astimezone(self.backend.ZoneInfo("Europe/Moscow")).date().isoformat(),
                    "prompt_template": self.backend.build_default_job_template("research_watch"),
                    "parameters": {
                        "subject": "Собери информацию из СМИ по HR-трендам",
                        "angle": "упоминания в СМИ, значимые события, сигналы рынка и изменения позиции",
                        "output": "структурированная краткая сводка без лишней воды",
                    },
                    "recipients": [{"recipient_type": "owner", "target_value": "self", "label": "Только владелец"}],
                },
            )
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "HR-тренды",
            [
                ("user", "Собери информацию из СМИ по HR-трендам", {"user_text": "Собери информацию из СМИ по HR-трендам"}),
                ("assistant", "Подготовила обзор по теме.", {}),
                ("user", "Запусти сейчас эту задачу и дай ответ сюда", {"user_text": "Запусти сейчас эту задачу и дай ответ сюда"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            before_count = int(conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE user_id = ?", (user_id,)).fetchone()["c"])
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[2], message_ids[3], "{}", ts),
            )
            task_id = int(cur.fetchone()[0])

        original_execute_job = self.backend.execute_job
        self.backend.execute_job = lambda job_id, triggered_by_user_id, trigger_type: {
            "job_id": job_id,
            "trigger_type": trigger_type,
            "summary": "Короткий тестовый результат запуска",
            "result_text": "Короткий тестовый результат запуска",
        }
        try:
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.execute_job = original_execute_job

        with self.backend.db_connect() as conn:
            after_count = int(conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE user_id = ?", (user_id,)).fetchone()["c"])
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (message_ids[3],)).fetchone()

        self.assertEqual(after_count, before_count)
        self.assertIn("Запустила существующую задачу", assistant["content"])
        self.assertIn("Короткий тестовый результат запуска", assistant["content"])
        assistant_meta = json.loads(assistant["meta_json"] or "{}")
        self.assertEqual(assistant_meta.get("message_kind"), "job_run_now")
        self.assertEqual(int(assistant_meta.get("created_job_id")), int(existing["id"]))
        self.assertEqual(assistant_meta.get("downstream"), "chat:job_run_now")

    def test_chat_recurring_request_uses_recent_messages_context(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Мониторинг в СМИ",
            [
                ("user", "Собери информацию из СМИ по Виктории и её упоминаниям", {"user_text": "Собери информацию из СМИ по Виктории и её упоминаниям"}),
                ("assistant", "Собрала стартовый обзор.", {}),
                ("user", "Давай поставим это как регулярный мониторинг", {"user_text": "Давай поставим это как регулярный мониторинг"}),
                ("user", "Еженедельно по пятницам в 08:30", {"user_text": "Еженедельно по пятницам в 08:30"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        user_message_id = message_ids[3]
        assistant_message_id = message_ids[4]
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, user_message_id, assistant_message_id, "{}", ts),
            )
            task_id = int(cur.fetchone()[0])

        processed = self.backend.process_chat_task(task_id)
        self.assertTrue(processed)

        with self.backend.db_connect() as conn:
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
            jobs = conn.execute("SELECT name, timezone, schedule_kind, time_of_day, days_of_week_json FROM jobs WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()

        assistant_meta = json.loads(assistant["meta_json"] or "{}")
        self.assertEqual(assistant_meta.get("message_kind"), "job_created")
        self.assertEqual(assistant_meta.get("downstream"), "chat:job_created")
        self.assertTrue(jobs)
        latest = jobs[0]
        self.assertIn("Виктории", latest["name"])
        self.assertEqual(latest["timezone"], "Europe/Moscow")
        self.assertEqual(latest["schedule_kind"], "weekly")
        self.assertEqual(latest["time_of_day"], "08:30")
        self.assertEqual(json.loads(latest["days_of_week_json"]), ["fri"])

    def test_chat_recurring_request_with_explicit_schedule_takes_priority_over_collection_clarification(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Комплаенс мониторинг",
            [
                (
                    "user",
                    "Я бы хотел создать регулярную задачу, чтобы ты каждый день в 9:00 по Москве собирал мне дайджест новостей из сферы автоматизированного анализа рисков и контрагентов, благонадежности и комплаенс, а также новые продукты и особенно решения ИИ для этой области. Первую итерацию сбора сделай сейчас, а остальные - ежедневно в 9 утра.",
                    {"user_text": "Я бы хотел создать регулярную задачу, чтобы ты каждый день в 9:00 по Москве собирал мне дайджест новостей из сферы автоматизированного анализа рисков и контрагентов, благонадежности и комплаенс, а также новые продукты и особенно решения ИИ для этой области. Первую итерацию сбора сделай сейчас, а остальные - ежедневно в 9 утра."},
                ),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[0], message_ids[1], "{}", ts),
            )
            task_id = int(cur.fetchone()[0])

        self.assertTrue(self.backend.process_chat_task(task_id))

        with self.backend.db_connect() as conn:
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (message_ids[1],)).fetchone()
            jobs = conn.execute("SELECT name, schedule_kind, time_of_day FROM jobs WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()

        meta = json.loads(assistant["meta_json"] or "{}")
        self.assertEqual(meta.get("message_kind"), "job_created")
        self.assertEqual(meta.get("downstream"), "chat:job_created")
        self.assertTrue(jobs)
        self.assertEqual(jobs[0]["schedule_kind"], "daily")
        self.assertEqual(jobs[0]["time_of_day"], "09:00")
        self.assertIn("Создала задачу", assistant["content"])

    def test_chat_research_request_does_not_create_recurring_job_without_explicit_schedule_intent(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Подбор каналов",
            [
                ("user", "Какой массив данных по телеграмм каналам у тебя есть?", {"user_text": "Какой массив данных по телеграмм каналам у тебя есть?"}),
                ("assistant", "Могу подобрать актуальную выборку по теме.", {}),
                ("user", "Подбери перечень телеграмм-каналов, который актуально мониторить для технологической практики", {"user_text": "Подбери перечень телеграмм-каналов, который актуально мониторить для технологической практики"}),
                ("assistant", "Вот стартовая подборка.", {}),
                ("user", "найди перечень каналов крупных вендоров и интеграторов для мониторинга", {"user_text": "найди перечень каналов крупных вендоров и интеграторов для мониторинга"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        user_message_id = message_ids[4]
        assistant_message_id = message_ids[5]
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            before_jobs = int(conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE user_id = ?", (user_id,)).fetchone()["c"])
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, user_message_id, assistant_message_id, "{}", ts),
            )
            task_id = int(cur.fetchone()[0])

        processed = self.backend.process_chat_task(task_id)
        self.assertTrue(processed)

        with self.backend.db_connect() as conn:
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
            after_jobs = int(conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE user_id = ?", (user_id,)).fetchone()["c"])

        self.assertEqual(before_jobs, after_jobs)
        self.assertNotIn("Создала задачу", assistant["content"])
        meta = json.loads(assistant["meta_json"] or "{}")
        self.assertNotEqual(meta.get("message_kind"), "job_created")

    def test_profile_threads_and_jobs_read_only_mode(self):
        token = self.login()

        me = self.client.get("/api/me", headers=self.auth_headers(token))
        self.assertEqual(me.status_code, 200)
        me_json = me.get_json()
        self.assertEqual(me_json["user"]["email"], "misha@demo.local")
        self.assertIn("assistant_profile", me_json["user"])

        bootstrap = self.client.get("/api/bootstrap", headers=self.auth_headers(token))
        self.assertEqual(bootstrap.status_code, 200)
        refs = bootstrap.get_json()["references"]
        self.assertIn("assistant_tones", refs)
        self.assertIn("assistant_answer_depths", refs)
        self.assertIn("assistant_interaction_modes", refs)
        self.assertIn("dashboard_grammar", refs)

        patch_me = self.client.patch(
            "/api/me",
            headers=self.auth_headers(token),
            json={
                "assistant_profile": {
                    "tone": "business",
                    "answer_depth": "detailed",
                    "interaction_mode": "compare_options",
                    "about_user": "Любит проверяемые ответы",
                }
            },
        )
        self.assertEqual(patch_me.status_code, 200)
        patch_json = patch_me.get_json()
        self.assertEqual(patch_json["user"]["assistant_profile"]["tone"], "business")
        self.assertEqual(patch_json["user"]["style_summary"]["tone"], "Делово")

        invalid_patch = self.client.patch(
            "/api/me",
            headers=self.auth_headers(token),
            json={"assistant_profile": {"tone": "invalid-tone"}},
        )
        self.assertEqual(invalid_patch.status_code, 400)
        self.assertEqual(invalid_patch.get_json()["error"], "assistant_profile_invalid_tone")

        stale_profile = self.client.patch(
            "/api/me",
            headers=self.auth_headers(token),
            json={"version": 1, "goals": "Устаревшее сохранение не должно пройти"},
        )
        self.assertEqual(stale_profile.status_code, 409)
        self.assertEqual(stale_profile.get_json()["error"], "version_conflict")

        threads = self.client.get("/api/threads", headers=self.auth_headers(token))
        self.assertEqual(threads.status_code, 200)
        self.assertGreaterEqual(len(threads.get_json()["threads"]), 1)
        first_thread = next(thread for thread in threads.get_json()["threads"] if thread.get("thread_kind") != 'job')
        self.assertEqual(first_thread.get("version"), 1)

        renamed_thread = self.client.patch(
            f"/api/threads/{first_thread['id']}",
            headers=self.auth_headers(token),
            json={"title": "Переименованный чат", "version": 1},
        )
        self.assertEqual(renamed_thread.status_code, 200)
        self.assertEqual(renamed_thread.get_json()["thread"]["title"], "Переименованный чат")
        self.assertEqual(renamed_thread.get_json()["thread"]["version"], 2)

        stale_thread = self.client.patch(
            f"/api/threads/{first_thread['id']}",
            headers=self.auth_headers(token),
            json={"archived": True, "version": 1},
        )
        self.assertEqual(stale_thread.status_code, 409)
        self.assertEqual(stale_thread.get_json()["error"], "version_conflict")

        jobs = self.client.get('/api/jobs', headers=self.auth_headers(token))
        self.assertEqual(jobs.status_code, 200)

        created_job = self.client.post(
            "/api/jobs",
            headers=self.auth_headers(token),
            json={
                "name": "Smoke job",
                "description": "Проверка end-to-end",
                "job_type": "custom",
                "visibility": "private",
                "status": "active",
                "schedule_kind": "daily",
                "time_of_day": "09:15",
                "timezone": "Europe/Moscow",
                "start_date": "2026-06-03",
                "parameters": {"goal": "Проверить тестовую задачу", "context": "Только smoke test"},
                "recipients": [{"recipient_type": "owner", "target_value": "self", "label": "Только владелец"}],
            },
        )
        self.assertEqual(created_job.status_code, 201)
        created_job_json = created_job.get_json()["job"]
        self.assertEqual(created_job_json["name"], "Smoke job")
        self.assertEqual(created_job_json["role"], "owner")

        thread_id = threads.get_json()["threads"][0]["id"]
        message = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Проверь, что чат отвечает."},
        )
        self.assertEqual(message.status_code, 201)
        self.assertIn("assistant_message", message.get_json())

        dashboard_clarification = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Построй дашборд по локальной аналитике."},
        )
        self.assertEqual(dashboard_clarification.status_code, 201)
        clarification_body = dashboard_clarification.get_json()
        self.assertEqual(clarification_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(clarification_body["assistant_message"]["meta"].get("pending"))
        self.assertTrue(self.backend.process_chat_task(clarification_body["chat_task"]["id"]))
        clarification_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertEqual(clarification_json["meta"]["message_kind"], "clarification_request")
        self.assertEqual(clarification_json["meta"]["clarification_title"], "Уточните условия дашборда")
        self.assertEqual(
            clarification_json["meta"]["clarification_options"],
            ["Уточнить локальный источник и период", "Переключиться на внешний обзор по открытым источникам"],
        )
        self.assertNotIn("clarification_actions", clarification_json["meta"])
        self.assertIn("источник или набор данных", clarification_json["meta"]["clarification_prompt"])
        self.assertIn("Если вы не знаете, есть ли локальные данные", clarification_json["meta"]["clarification_prompt"])
        self.assertIn("Если локальных данных нет или нужен общий внешний обзор", clarification_json["meta"]["clarification_prompt"])

        text_review_reply = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Проверь общую текстовку письма: в тексте есть Telegram, интернет и глубокая аналитика, но задача — просто отредактировать письмо."},
        )
        self.assertEqual(text_review_reply.status_code, 201)
        text_review_body = text_review_reply.get_json()
        self.assertEqual(text_review_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(self.backend.process_chat_task(text_review_body["chat_task"]["id"]))
        text_review_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertNotEqual(text_review_json["meta"].get("message_kind"), "dashboard_result")
        self.assertNotEqual(text_review_json["meta"].get("message_kind"), "clarification_request")
        self.assertNotIn("dashboard", text_review_json["meta"])
        self.assertFalse(self.backend.is_dashboard_request("Сделай аналитику рынка LegalAI за неделю."))
        self.assertFalse(self.backend.is_dashboard_request("Нужна глубокая аналитика по Telegram-каналам, но без дашборда."))
        self.assertTrue(self.backend.is_dashboard_request("Собери дашборд по рынку LegalAI."))

        generic_scoped_reply = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Построй дашборд по CRM за 30 дней: воронка, конверсия по этапам и топ менеджеров."},
        )
        self.assertEqual(generic_scoped_reply.status_code, 201)
        generic_scoped_body = generic_scoped_reply.get_json()
        self.assertEqual(generic_scoped_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(self.backend.process_chat_task(generic_scoped_body["chat_task"]["id"]))
        generic_scoped_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertNotEqual(generic_scoped_json["meta"].get("message_kind"), "clarification_request")
        self.assertEqual(generic_scoped_json["meta"]["dashboard"]["kind"], "external_research_dashboard")
        self.assertEqual(generic_scoped_json["meta"]["dashboard_policy"]["source_mode"], "local_first")
        self.assertEqual(generic_scoped_json["meta"].get("dashboard_grammar"), "adaptive_v1")
        self.assertEqual(generic_scoped_json["meta"]["dashboard"].get("grammar_version"), "adaptive_v1")
        self.assertIn(generic_scoped_json["meta"]["dashboard"].get("intent"), ["trend", "segmentation", "comparison", "market_overview", "evidence_board"])
        self.assertIn("selection_policy", generic_scoped_json["meta"]["dashboard"])
        self.assertGreaterEqual(len(generic_scoped_json["meta"]["dashboard"].get("sections", [])), 3)

        global_only_dashboard = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Собери из интернета данные по рынку LegalAI и дай дашборд.", "source_mode": "global_only", "explicit_source_ids": ["web_research"]},
        )
        self.assertEqual(global_only_dashboard.status_code, 201)
        global_only_body = global_only_dashboard.get_json()
        self.assertEqual(global_only_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(self.backend.process_chat_task(global_only_body["chat_task"]["id"]))
        global_only_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertEqual(global_only_json["meta"]["message_kind"], "dashboard_result")
        self.assertEqual(global_only_json["meta"]["dashboard"]["kind"], "external_research_dashboard")
        self.assertEqual(global_only_json["meta"]["dashboard_policy"]["source_mode"], "global_only")
        self.assertEqual(global_only_json["meta"]["dashboard_policy"]["explicit_source_ids"], ["web_research"])
        self.assertEqual(global_only_json["meta"]["dashboard_policy"]["allowed_sources"], ["web_research"])
        self.assertEqual(global_only_json["meta"]["dashboard_builder"], "web_research")
        self.assertEqual(global_only_json["meta"].get("dashboard_grammar"), "adaptive_v1")
        self.assertEqual(global_only_json["meta"]["dashboard"].get("grammar_version"), "adaptive_v1")
        self.assertIn("selection_policy", global_only_json["meta"]["dashboard"])
        self.assertGreaterEqual(len(global_only_json["meta"]["dashboard"].get("sections", [])), 3)

        internet_dashboard = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Собери из интернета данные по рынку LegalAI и дай дашборд."},
        )
        self.assertEqual(internet_dashboard.status_code, 201)
        internet_dashboard_body = internet_dashboard.get_json()
        self.assertEqual(internet_dashboard_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(self.backend.process_chat_task(internet_dashboard_body["chat_task"]["id"]))
        internet_dashboard_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertEqual(internet_dashboard_json["meta"]["message_kind"], "dashboard_result")
        self.assertEqual(internet_dashboard_json["meta"]["dashboard"]["kind"], "external_research_dashboard")
        self.assertEqual(internet_dashboard_json["meta"]["dashboard_policy"]["source_mode"], "local_first")
        self.assertEqual(internet_dashboard_json["meta"]["dashboard_builder"], "web_research")

        local_only_dashboard = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Собери из интернета данные по рынку LegalAI и дай дашборд.", "source_mode": "local_only"},
        )
        self.assertEqual(local_only_dashboard.status_code, 201)
        local_only_body = local_only_dashboard.get_json()
        self.assertEqual(local_only_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(self.backend.process_chat_task(local_only_body["chat_task"]["id"]))
        local_only_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertEqual(local_only_json["meta"]["message_kind"], "clarification_request")
        self.assertTrue(local_only_json["meta"].get("policy_blocked_global"))

        csv_dashboard = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            data={
                "content": "Построй дашборд по этому файлу.",
                "files": (io.BytesIO("category,amount,region\nA,10,North\nB,20,South\nA,15,North\nC,5,East\n".encode("utf-8")), "sales.csv"),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(csv_dashboard.status_code, 201)
        csv_dashboard_body = csv_dashboard.get_json()
        self.assertEqual(csv_dashboard_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(self.backend.process_chat_task(csv_dashboard_body["chat_task"]["id"]))
        csv_dashboard_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertEqual(csv_dashboard_json["meta"]["message_kind"], "dashboard_result")
        self.assertEqual(csv_dashboard_json["meta"]["dashboard"]["kind"], "generic_dataset_analytics")
        self.assertIn("sales.csv", csv_dashboard_json["meta"]["dashboard"]["title"])
        self.assertGreater(len(csv_dashboard_json["meta"]["dashboard"].get("summary_cards", [])), 0)
        self.assertGreater(len(csv_dashboard_json["meta"]["dashboard"].get("sections", [])), 0)

        upload_message = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            data={
                "content": "Разбери приложенный файл.",
                "files": (io.BytesIO("строка 1\nстрока 2".encode("utf-8")), "note.txt"),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(upload_message.status_code, 201)
        upload_json = upload_message.get_json()
        self.assertEqual(len(upload_json.get("user_attachments", [])), 1)
        self.assertEqual(upload_json["user_attachments"][0]["original_name"], "note.txt")
        self.assertIn("assistant_message", upload_json)
        self.assertIsNotNone(upload_json["assistant_message"].get("id"))
        self.assertEqual(upload_json["assistant_message"]["role"], "assistant")

        user_files = self.client.get('/api/files', headers=self.auth_headers(token))
        self.assertEqual(user_files.status_code, 200)
        files_json = user_files.get_json()["files"]
        self.assertGreaterEqual(len(files_json), 1)
        self.assertEqual(files_json[0]["original_name"], "note.txt")
        self.assertTrue(files_json[0]["download_url"].startswith(f"/api/files/{files_json[0]['id']}/download"))

        download_file = self.client.get(files_json[0]["download_url"], headers=self.auth_headers(token))
        self.assertEqual(download_file.status_code, 200)
        self.assertIn("attachment", download_file.headers.get("Content-Disposition", ""))
        self.assertEqual(download_file.data.decode('utf-8'), "строка 1\nстрока 2")
        download_file.close()

        reuse_message = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": "Используй тот же файл ещё раз.", "existing_file_ids": [files_json[0]["id"]]},
        )
        self.assertEqual(reuse_message.status_code, 201)
        reuse_json = reuse_message.get_json()
        self.assertEqual(len(reuse_json.get("user_attachments", [])), 1)
        self.assertTrue(reuse_json["user_attachments"][0].get("reused"))
        self.assertIn("assistant_message", reuse_json)
        self.assertIsNotNone(reuse_json["assistant_message"].get("id"))

        assistant_media_path = Path(self.tempdir) / 'assistant-report.txt'
        assistant_media_path.write_text('assistant file body', encoding='utf-8')
        assistant_media = self.client.post(
            f"/api/threads/{thread_id}/messages",
            headers=self.auth_headers(token),
            json={"content": f"Подготовь файл для ответа.\nMEDIA:{assistant_media_path}"},
        )
        self.assertEqual(assistant_media.status_code, 201)
        assistant_body = assistant_media.get_json()
        self.assertEqual(assistant_body["assistant_message"]["meta"]["message_kind"], "processing_status")
        self.assertTrue(self.backend.process_chat_task(assistant_body["chat_task"]["id"]))
        assistant_json = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
        self.assertNotIn('MEDIA:', assistant_json['content'])
        self.assertEqual(len(assistant_json['meta']['attachments']), 1)
        attachment = assistant_json['meta']['attachments'][0]
        self.assertTrue(attachment['assistant_generated'])
        self.assertIn('/api/messages/', attachment['download_url'])
        downloaded = self.client.get(attachment['download_url'], headers=self.auth_headers(token))
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.data, b'assistant file body')
        downloaded.close()

        admin_token = self.login('admin@demo.local')
        policy_before = self.client.get('/api/admin/dashboard-policy', headers=self.auth_headers(admin_token))
        self.assertEqual(policy_before.status_code, 200)
        original_policy = policy_before.get_json()['dashboard_policy']
        roundtrip_policy = self.client.patch(
            '/api/admin/dashboard-policy',
            headers=self.auth_headers(admin_token),
            json={
                'source_mode': original_policy['source_mode'],
                'default_global_source': original_policy['default_global_source'],
                'allowed_sources': list(original_policy['allowed_sources']),
                'connector_targets': dict(original_policy.get('connector_targets') or {}),
            },
        )
        self.assertEqual(roundtrip_policy.status_code, 200)
        self.assertEqual(roundtrip_policy.get_json()['dashboard_policy']['allowed_sources'], original_policy['allowed_sources'])
        self.assertIn('internal_connector', roundtrip_policy.get_json()['dashboard_policy']['connector_targets'])

        legacy_policy = self.client.patch(
            '/api/admin/dashboard-policy',
            headers=self.auth_headers(admin_token),
            json={
                'source_mode': 'local_first',
                'default_global_source': 'web_research',
                'allowed_sources': ['google_api_connector', 'web_research'],
            },
        )
        self.assertEqual(legacy_policy.status_code, 200)
        self.assertEqual(legacy_policy.get_json()['dashboard_policy']['allowed_sources'], ['external_connector', 'web_research'])

        connector_move_policy = self.client.patch(
            '/api/admin/dashboard-policy',
            headers=self.auth_headers(admin_token),
            json={
                'source_mode': 'global_only',
                'default_global_source': 'web_research',
                'allowed_sources': ['web_research', 'external_connector'],
                'connector_targets': {
                    'internal_connector': [],
                    'external_connector': ['hermes_api'],
                },
                'connector_group_overrides': {
                    'hermes_api': 'external_connector',
                },
            },
        )
        self.assertEqual(connector_move_policy.status_code, 200)
        moved_policy = connector_move_policy.get_json()['dashboard_policy']
        self.assertEqual(moved_policy['source_mode'], 'global_only')
        self.assertEqual(moved_policy['allowed_sources'], ['web_research', 'external_connector'])
        self.assertEqual(moved_policy['default_global_source'], 'web_research')
        self.assertEqual(moved_policy['connector_targets']['internal_connector'], [])
        self.assertEqual(moved_policy['connector_targets']['external_connector'], ['hermes_api'])

        restore_policy = self.client.patch(
            '/api/admin/dashboard-policy',
            headers=self.auth_headers(admin_token),
            json={
                'source_mode': original_policy['source_mode'],
                'default_global_source': original_policy['default_global_source'],
                'allowed_sources': list(original_policy['allowed_sources']),
                'connector_targets': dict(original_policy.get('connector_targets') or {}),
            },
        )
        self.assertEqual(restore_policy.status_code, 200)

        admin_health = self.client.get('/api/admin/health', headers=self.auth_headers(admin_token))
        self.assertEqual(admin_health.status_code, 200)
        admin_health_json = admin_health.get_json()
        self.assertEqual(admin_health_json['status'], 'ok')
        self.assertIn('active_users_7d', admin_health_json)
        self.assertIn('failed_job_runs_7d', admin_health_json)

        def fetch_chat_notice(_: int) -> tuple[int, dict]:
            with self.backend.app.test_client() as client:
                response = client.get('/api/admin/chat-notice', headers=self.auth_headers(admin_token))
                return response.status_code, response.get_json() or {}

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(fetch_chat_notice, range(12)))
        for status_code, payload in responses:
            self.assertEqual(status_code, 200)
            self.assertIn('chat_notice', payload)

        second_admin_token = self.login('admin@demo.local')
        third_admin_token = self.login('admin@demo.local')
        self.assertNotEqual(admin_token, second_admin_token)
        self.assertNotEqual(second_admin_token, third_admin_token)
        with self.backend.db_connect() as conn:
            active_admin_sessions = conn.execute(
                "SELECT COUNT(*) AS c FROM sessions WHERE user_id = ? AND revoked_at IS NULL",
                (2,),
            ).fetchone()['c']
        self.assertEqual(active_admin_sessions, 1)

    def test_jobs_write_endpoints_rejected_in_current_mode(self):
        outsider_email = "outsider@demo.local"
        admin_email = "job-admin@demo.local"
        outsider_id = self.create_user(outsider_email)
        self.create_user(admin_email, role='admin')

        owner_token = self.login()
        outsider_token = self.login(outsider_email)
        admin_token = self.login(admin_email)

        created = self.client.post(
            "/api/jobs",
            headers=self.auth_headers(owner_token),
            json={
                "name": "Restricted shared job",
                "display_name": "Понятный клиентский мониторинг",
                "description": "Shared with explicit access",
                "job_type": "custom",
                "visibility": "shared",
                "status": "active",
                "schedule_kind": "daily",
                "time_of_day": "09:00",
                "timezone": "Europe/Moscow",
                "start_date": "2026-06-03",
                "parameters": {"goal": "Проверка прав", "context": "Аутсайдер получает только просмотр"},
                "access": [{"user_id": outsider_id, "role": "viewer"}],
                "recipients": [
                    {"recipient_type": "owner", "target_value": "self", "label": "Владелец"},
                    {"recipient_type": "fixed_user", "target_value": str(outsider_id), "label": outsider_email},
                ],
            },
        )
        self.assertEqual(created.status_code, 201)
        job_id = created.get_json()["job"]["id"]

        outsider_jobs = self.client.get('/api/jobs', headers=self.auth_headers(outsider_token))
        self.assertEqual(outsider_jobs.status_code, 200)
        outsider_items = outsider_jobs.get_json()["jobs"]
        self.assertTrue(any(item["id"] == job_id for item in outsider_items))
        visible_job = next(item for item in outsider_items if item["id"] == job_id)
        self.assertEqual(visible_job["display_name"], "Понятный клиентский мониторинг")

        outsider_patch = self.client.patch(
            f'/api/jobs/{job_id}',
            headers=self.auth_headers(outsider_token),
            json={"description": "Outsider should not edit"},
        )
        self.assertEqual(outsider_patch.status_code, 403)

        admin_patch = self.client.patch(
            f'/api/jobs/{job_id}',
            headers=self.auth_headers(admin_token),
            json={"description": "Admin can edit", "display_name": "Общее название для всех", "version": 1},
        )
        self.assertEqual(admin_patch.status_code, 200)
        self.assertEqual(admin_patch.get_json()["job"]["description"], "Admin can edit")
        self.assertEqual(admin_patch.get_json()["job"]["display_name"], "Общее название для всех")
        self.assertEqual(admin_patch.get_json()["job"]["version"], 2)

        stale_job_patch = self.client.patch(
            f'/api/jobs/{job_id}',
            headers=self.auth_headers(owner_token),
            json={"description": "Stale owner update", "version": 1},
        )
        self.assertEqual(stale_job_patch.status_code, 409)
        self.assertEqual(stale_job_patch.get_json()["error"], "version_conflict")

        outsider_detail = self.client.get(f'/api/jobs/{job_id}', headers=self.auth_headers(outsider_token))
        self.assertEqual(outsider_detail.status_code, 200)
        self.assertEqual(outsider_detail.get_json()['job']['display_name'], 'Общее название для всех')

        owner_run = self.client.post(f'/api/jobs/{job_id}/run', headers=self.auth_headers(owner_token))
        self.assertEqual(owner_run.status_code, 200)

        outsider_run = self.client.post(f'/api/jobs/{job_id}/run', headers=self.auth_headers(outsider_token))
        self.assertEqual(outsider_run.status_code, 403)

        outsider_threads = self.client.get('/api/threads?include_archived=1', headers=self.auth_headers(outsider_token))
        self.assertEqual(outsider_threads.status_code, 200)
        self.assertTrue(any(thread.get('job_id') == job_id for thread in outsider_threads.get_json()['threads']))

    def test_hermes_cron_job_admin_recipients_create_separate_thread_and_deliver_output(self):
        admin_token = self.login('admin@demo.local', 'demo123')
        recipient_user_id = self.create_user('hermes-cron-recipient@demo.local')
        hermes_job = {
            'id': 'hermes-cron-test',
            'name': 'Ежедневный TG digest',
            'prompt': 'Собери digest',
            'deliver': 'origin',
            'created_at': '2026-06-14T15:00:00+00:00',
            'last_run_at': '2026-06-14T15:00:00+00:00',
            'last_status': 'success',
            'last_error': '',
            'schedule_display': '0 15 * * *',
            'next_run_at': '2026-06-15T15:00:00+00:00',
        }
        cron_output_dir = Path(self.tempdir) / 'cron-output'
        job_output_dir = cron_output_dir / hermes_job['id']
        job_output_dir.mkdir(parents=True, exist_ok=True)
        (job_output_dir / '2026-06-14_15-00-37.md').write_text(
            '# Cron Job: daily-digest\n\n## Response\n\nГотово. Дайджест собран и доставлен.',
            encoding='utf-8',
        )

        def fake_update(job_id, updates):
            merged = dict(hermes_job)
            merged.update(updates or {})
            return merged

        with patch.object(self.backend, 'HERMES_CRON_OUTPUT_DIR', cron_output_dir), \
             patch.object(self.backend, 'hermes_get_job', return_value=hermes_job), \
             patch.object(self.backend, 'hermes_update_job', side_effect=fake_update):
            updated = self.client.patch(
                '/api/jobs/hermes-cron-test',
                headers=self.auth_headers(admin_token),
                json={
                    'recipients': [
                        {'recipient_type': 'fixed_user', 'target_value': str(recipient_user_id), 'label': 'Получатель дайджеста'}
                    ]
                },
            )
            self.assertEqual(updated.status_code, 200)
            payload = updated.get_json()['job']
            self.assertFalse(payload['read_only'])
            self.assertTrue(any(item['recipient_type'] == 'fixed_user' and str(item['target_value']) == str(recipient_user_id) for item in payload['recipients']))

            detailed = self.client.get('/api/jobs/hermes-cron-test', headers=self.auth_headers(admin_token))
            self.assertEqual(detailed.status_code, 200)

        with self.backend.db_connect() as conn:
            thread_row = conn.execute(
                'SELECT id, title, user_id, external_job_id FROM threads WHERE user_id = ? AND external_job_id = ?',
                (recipient_user_id, 'hermes-cron-test'),
            ).fetchone()
            self.assertIsNotNone(thread_row)
            self.assertEqual(thread_row['title'], 'Ежедневный TG digest')
            message_row = conn.execute(
                'SELECT content FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT 1',
                (thread_row['id'],),
            ).fetchone()
            self.assertIsNotNone(message_row)
            self.assertIn('Дайджест собран и доставлен', message_row['content'])

    def test_job_self_subscribe_settings_and_thread_lifecycle(self):
        viewer_email = 'self-sub-viewer@demo.local'
        viewer_id = self.create_user(viewer_email)
        owner_token = self.login()
        viewer_token = self.login(viewer_email)

        created = self.client.post(
            '/api/jobs',
            headers=self.auth_headers(owner_token),
            json={
                'name': 'Self-subscribe controlled job',
                'description': 'Проверка управляемой самоподписки',
                'job_type': 'custom',
                'visibility': 'shared',
                'status': 'active',
                'schedule_kind': 'daily',
                'time_of_day': '09:00',
                'timezone': 'Europe/Moscow',
                'start_date': '2026-06-03',
                'prompt_template': 'Проверка самоподписки',
                'parameters': {'goal': 'Проверка self-subscribe', 'context': 'viewer flow'},
                'self_subscribe_enabled': False,
                'self_subscribe_scope': 'disabled',
                'access': [{'user_id': viewer_id, 'role': 'viewer'}],
                'recipients': [{'recipient_type': 'owner', 'target_value': 'self', 'label': 'Владелец'}],
            },
        )
        self.assertEqual(created.status_code, 201)
        job_id = created.get_json()['job']['id']

        detail_disabled = self.client.get(f'/api/jobs/{job_id}', headers=self.auth_headers(viewer_token))
        self.assertEqual(detail_disabled.status_code, 200)
        self.assertFalse(detail_disabled.get_json()['job']['can_self_subscribe'])
        self.assertFalse(detail_disabled.get_json()['job']['self_subscribe_enabled'])
        self.assertEqual(detail_disabled.get_json()['job']['self_subscribe_scope'], 'disabled')

        subscribe_disabled = self.client.post(f'/api/jobs/{job_id}/subscribe', headers=self.auth_headers(viewer_token))
        self.assertEqual(subscribe_disabled.status_code, 403)
        self.assertEqual(subscribe_disabled.get_json()['error'], 'job_self_subscribe_forbidden')

        enabled = self.client.patch(
            f'/api/jobs/{job_id}',
            headers=self.auth_headers(owner_token),
            json={'self_subscribe_enabled': True, 'self_subscribe_scope': 'visible_users'},
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.get_json()['job']['self_subscribe_enabled'])
        self.assertEqual(enabled.get_json()['job']['self_subscribe_scope'], 'visible_users')

        detail_enabled = self.client.get(f'/api/jobs/{job_id}', headers=self.auth_headers(viewer_token))
        self.assertEqual(detail_enabled.status_code, 200)
        self.assertTrue(detail_enabled.get_json()['job']['can_self_subscribe'])
        self.assertFalse(detail_enabled.get_json()['job']['is_subscribed'])

        threads_before = self.client.get('/api/threads?include_archived=1', headers=self.auth_headers(viewer_token))
        self.assertEqual(threads_before.status_code, 200)
        self.assertFalse(any(thread.get('job_id') == job_id for thread in threads_before.get_json()['threads']))

        subscribed = self.client.post(f'/api/jobs/{job_id}/subscribe', headers=self.auth_headers(viewer_token))
        self.assertEqual(subscribed.status_code, 200)
        self.assertEqual(subscribed.get_json()['status'], 'subscribed')
        self.assertTrue(subscribed.get_json()['job']['is_subscribed'])

        threads_after = self.client.get('/api/threads?include_archived=1', headers=self.auth_headers(viewer_token))
        self.assertEqual(threads_after.status_code, 200)
        matching_threads = [thread for thread in threads_after.get_json()['threads'] if thread.get('job_id') == job_id and thread.get('thread_kind') == 'job']
        self.assertEqual(len(matching_threads), 1)

        with self.backend.db_connect() as conn:
            job_row = self.backend.get_job_by_id(conn, job_id)
            first_thread_id = self.backend.ensure_job_thread_for_user(conn, job_row, viewer_id)
            second_thread_id = self.backend.ensure_job_thread_for_user(conn, job_row, viewer_id)
            self.assertEqual(first_thread_id, second_thread_id)
            duplicate_rows = conn.execute("SELECT id FROM threads WHERE user_id = ? AND job_id = ?", (viewer_id, job_id)).fetchall()
            self.assertEqual(len(duplicate_rows), 1)

        unsubscribed = self.client.post(f'/api/jobs/{job_id}/unsubscribe', headers=self.auth_headers(viewer_token))
        self.assertEqual(unsubscribed.status_code, 200)
        self.assertEqual(unsubscribed.get_json()['status'], 'unsubscribed')
        self.assertFalse(unsubscribed.get_json()['job']['is_subscribed'])

        threads_after_unsub = self.client.get('/api/threads?include_archived=1', headers=self.auth_headers(viewer_token))
        self.assertEqual(threads_after_unsub.status_code, 200)
        self.assertFalse(any(thread.get('job_id') == job_id for thread in threads_after_unsub.get_json()['threads']))


    def test_service_info_and_user_import(self):
        admin_email = 'admin-import@demo.local'
        self.create_user(admin_email, role='admin')
        token = self.login(admin_email)

        service_info = self.client.get('/api/service-info')
        self.assertEqual(service_info.status_code, 200)
        self.assertEqual(service_info.get_json()['status'], 'ok')

        health = self.client.get('/api/health')
        self.assertEqual(health.status_code, 200)
        health_json = health.get_json()
        self.assertEqual(health_json['status'], 'ok')
        self.assertIn('jobs_count', health_json)
        self.assertIn('scheduler', health_json)
        self.assertIn('chat_processor', health_json)
        self.assertIn('alive', health_json['scheduler'])
        self.assertIn('alive', health_json['chat_processor'])
        self.assertIn('active_tasks', health_json['chat_processor'])
        self.assertIn('state', health_json['chat_processor'])

        with patch.object(self.backend, 'hermes_list_jobs', side_effect=RuntimeError('health must not call cron bridge')):
            health_without_cron = self.client.get('/api/health')
        self.assertEqual(health_without_cron.status_code, 200)
        self.assertEqual(health_without_cron.get_json()['jobs_count'], health_json['jobs_count'])

        sources = self.client.get('/api/admin/user-sources', headers=self.auth_headers(token))
        self.assertEqual(sources.status_code, 200)
        self.assertIn('database', sources.get_json())
        self.assertEqual(sources.get_json()['data_sources_sync']['write_on_get'], False)

        with patch.object(self.backend, 'hermes_list_jobs', side_effect=RuntimeError('admin user-sources must stay local')):
            sources_without_cron = self.client.get('/api/admin/user-sources', headers=self.auth_headers(token))
        self.assertEqual(sources_without_cron.status_code, 200)
        self.assertEqual(sources_without_cron.get_json()['hermes']['jobs_count'], sources.get_json()['hermes']['jobs_count'])
        self.assertIn('template_csv', sources.get_json()['import'])

        csv_payload = "email,name,role,team,title,timezone,language,goals,style,constraints,about_user,pinned,password\nimported@demo.local,Imported User,user,Ops,Analyst,Europe/Moscow,ru,Разобраться в задачах,Коротко и по делу,Без воды,Любит ясность,приоритет 1 | приоритет 2,temporary-pass-456\n"
        imported = self.client.post(
            '/api/admin/users/import',
            headers=self.auth_headers(token),
            json={'csv_text': csv_payload, 'default_password': 'temporary-pass-456'},
        )
        self.assertEqual(imported.status_code, 200)
        imported_json = imported.get_json()
        self.assertEqual(imported_json['created'], 1)

        update_csv_payload = "email,name,role,team,title,timezone,language,goals,style,constraints,about_user,pinned,password\nimported@demo.local,Imported User Updated,user,Ops,Senior Analyst,Europe/Moscow,ru,Уточнить задачи,Подробно и структурно,Без лишних действий,Любит ясность и контроль,приоритет 1 | приоритет 3,temporary-pass-456\n"
        updated_import = self.client.post(
            '/api/admin/users/import',
            headers=self.auth_headers(token),
            json={'csv_text': update_csv_payload, 'default_password': 'temporary-pass-456'},
        )
        self.assertEqual(updated_import.status_code, 200)
        updated_import_json = updated_import.get_json()
        self.assertEqual(updated_import_json['updated'], 1)
        self.assertEqual(updated_import_json['skipped'], 0)
        updated_item = next(item for item in updated_import_json['items'] if item['email'] == 'imported@demo.local')
        self.assertEqual(updated_item['status'], 'updated')

        imported_detail = self.client.get('/api/admin/users', headers=self.auth_headers(token))
        self.assertEqual(imported_detail.status_code, 200)
        imported_user = next(user for user in imported_detail.get_json()['users'] if user['email'] == 'imported@demo.local')
        self.assertEqual(imported_user['version'], 2)

        login_imported = self.client.post('/api/auth/login', json={'email': 'imported@demo.local', 'password': 'temporary-pass-456'})
        self.assertEqual(login_imported.status_code, 200)

    def test_admin_user_crud_and_reference_versioning(self):
        admin_email = 'admin-crud@demo.local'
        self.create_user(admin_email, role='admin')
        token = self.login(admin_email)

        created = self.client.post(
            '/api/admin/users',
            headers=self.auth_headers(token),
            json={
                'email': 'crud-check@demo.local',
                'password': 'temporary-pass-789',
                'role': 'user',
                'name': 'CRUD Check',
                'team': 'Architecture',
                'title': 'Verifier',
                'timezone': 'Europe/Moscow',
                'language': 'ru',
                'goals': 'Проверить админский контур',
                'style': 'Коротко и по делу',
                'constraints': 'Только русский интерфейс',
                'pinned': ['контроль версии'],
                'assistant_profile': {
                    'tone': 'business',
                    'answer_depth': 'detailed',
                    'interaction_mode': 'compare_options',
                    'about_user': 'Проверка сохранения nested assistant_profile',
                },
            },
        )
        self.assertEqual(created.status_code, 200)
        created_user = created.get_json()['user']
        self.assertEqual(created_user['version'], 1)
        self.assertEqual(created_user['assistant_profile']['about_user'], 'Проверка сохранения nested assistant_profile')
        user_id = created_user['id']

        updated = self.client.patch(
            f'/api/admin/users/{user_id}',
            headers=self.auth_headers(token),
            json={
                'email': 'crud-check@demo.local',
                'password': 'temporary-pass-789',
                'role': 'admin',
                'name': 'CRUD Check Updated',
                'team': 'Platform',
                'title': 'Admin Verifier',
                'timezone': 'Europe/Moscow',
                'language': 'ru',
                'goals': 'Проверить историю',
                'style': 'Подробно',
                'constraints': 'Нужна история изменений',
                'pinned': ['контроль версии', 'контроль истории'],
                'assistant_profile': {
                    'tone': 'business',
                    'answer_depth': 'detailed',
                    'interaction_mode': 'compare_options',
                    'about_user': 'Обновлённый nested assistant_profile',
                },
            },
        )
        self.assertEqual(updated.status_code, 200)
        updated_user = updated.get_json()['user']
        self.assertEqual(updated_user['version'], 2)
        self.assertEqual(updated_user['assistant_profile']['about_user'], 'Обновлённый nested assistant_profile')

        detail = self.client.get(f'/api/admin/users/{user_id}', headers=self.auth_headers(token))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()['user']['assistant_profile']['about_user'], 'Обновлённый nested assistant_profile')

        history = self.client.get(f'/api/admin/users/{user_id}/history', headers=self.auth_headers(token))
        self.assertEqual(history.status_code, 200)
        history_items = history.get_json()['history']
        self.assertGreaterEqual(len(history_items), 2)
        self.assertEqual(history_items[0]['change_type'], 'update')
        self.assertEqual(history_items[0]['snapshot']['version'], 2)

        threads_overview = self.client.get('/api/admin/threads', headers=self.auth_headers(token))
        self.assertEqual(threads_overview.status_code, 200)
        self.assertIn('threads', threads_overview.get_json())

        jobs_overview = self.client.get('/api/jobs', headers=self.auth_headers(token))
        self.assertEqual(jobs_overview.status_code, 200)
        self.assertIn('jobs', jobs_overview.get_json())

        item_key = 'feedback_reason_crud_check'
        created_reference = self.client.post(
            '/api/admin/reference-data/feedback_reasons/items',
            headers=self.auth_headers(token),
            json={
                'item_key': item_key,
                'label': 'Тестовая причина',
                'sort_order': 500,
                'is_active': True,
                'description': 'Проверка create/update/history',
            },
        )
        self.assertEqual(created_reference.status_code, 200)
        created_items = created_reference.get_json()['dataset']['items']
        created_ref = next(item for item in created_items if item['item_key'] == item_key)
        self.assertEqual(created_ref['version'], 1)

        updated_reference = self.client.patch(
            f'/api/admin/reference-data/feedback_reasons/items/{item_key}',
            headers=self.auth_headers(token),
            json={
                'label': 'Тестовая причина обновлена',
                'sort_order': 501,
                'is_active': False,
                'description': 'Проверка version после update',
            },
        )
        self.assertEqual(updated_reference.status_code, 200)
        updated_items = updated_reference.get_json()['dataset']['items']
        updated_ref = next(item for item in updated_items if item['item_key'] == item_key)
        self.assertEqual(updated_ref['version'], 2)
        self.assertFalse(updated_ref['is_active'])

        reference_history = self.client.get(
            f'/api/admin/reference-data/feedback_reasons/items/{item_key}/history',
            headers=self.auth_headers(token),
        )
        self.assertEqual(reference_history.status_code, 200)
        reference_history_items = reference_history.get_json()['history']
        self.assertGreaterEqual(len(reference_history_items), 2)
        self.assertEqual(reference_history_items[0]['change_type'], 'update')
        self.assertEqual(reference_history_items[0]['snapshot']['version'], 2)

    def test_admin_reference_items_bulk_status(self):
        admin_email = 'admin-ref-bulk@demo.local'
        self.create_user(admin_email, role='admin')
        token = self.login(admin_email)

        first_key = 'bulk_ref_one'
        second_key = 'bulk_ref_two'
        for item_key, label in ((first_key, 'Bulk Ref One'), (second_key, 'Bulk Ref Two')):
            created = self.client.post(
                '/api/admin/reference-data/feedback_reasons/items',
                headers=self.auth_headers(token),
                json={
                    'item_key': item_key,
                    'label': label,
                    'sort_order': 80,
                    'status': 'active',
                    'description': 'Проверка массового статуса справочников',
                },
            )
            self.assertEqual(created.status_code, 200)

        inactive = self.client.post(
            '/api/admin/reference-data/feedback_reasons/bulk-status',
            headers=self.auth_headers(token),
            json={'item_keys': [first_key, second_key], 'status': 'inactive'},
        )
        self.assertEqual(inactive.status_code, 200)
        inactive_items = inactive.get_json()['items']
        self.assertEqual(len(inactive_items), 2)
        self.assertTrue(all(item['status'] == 'inactive' for item in inactive_items))
        self.assertTrue(all(item['version'] == 2 for item in inactive_items))

        deleted = self.client.post(
            '/api/admin/reference-data/feedback_reasons/bulk-status',
            headers=self.auth_headers(token),
            json={'item_keys': [second_key], 'status': 'deleted'},
        )
        self.assertEqual(deleted.status_code, 200)
        deleted_item = deleted.get_json()['items'][0]
        self.assertEqual(deleted_item['status'], 'deleted')
        self.assertEqual(deleted_item['version'], 3)

        reference_history = self.client.get(
            f'/api/admin/reference-data/feedback_reasons/items/{second_key}/history',
            headers=self.auth_headers(token),
        )
        self.assertEqual(reference_history.status_code, 200)
        history_items = reference_history.get_json()['history']
        self.assertEqual(history_items[0]['change_type'], 'bulk_delete')
        self.assertEqual(history_items[1]['change_type'], 'bulk_inactivate')

    def test_admin_users_bulk_status(self):
        admin_email = 'admin-bulk@demo.local'
        self.create_user(admin_email, role='admin')
        token = self.login(admin_email)

        first = self.client.post(
            '/api/admin/users',
            headers=self.auth_headers(token),
            json={
                'email': 'bulk-one@demo.local',
                'password': 'temporary-pass-111',
                'role': 'user',
                'name': 'Bulk One',
                'team': 'Ops',
                'title': 'Operator',
                'timezone': 'Europe/Moscow',
                'language': 'ru',
                'goals': 'Проверить массовый перевод статусов',
                'style': 'Коротко и по делу',
                'constraints': 'Без англоязычного UI',
                'assistant_profile': {
                    'tone': 'business',
                    'answer_depth': 'short',
                    'interaction_mode': 'answer_directly',
                    'about_user': 'Первый для bulk update',
                },
            },
        )
        self.assertEqual(first.status_code, 200)
        first_user = first.get_json()['user']

        second = self.client.post(
            '/api/admin/users',
            headers=self.auth_headers(token),
            json={
                'email': 'bulk-two@demo.local',
                'password': 'temporary-pass-222',
                'role': 'user',
                'name': 'Bulk Two',
                'team': 'Ops',
                'title': 'Operator',
                'timezone': 'Europe/Moscow',
                'language': 'ru',
                'goals': 'Проверить массовое удаление из выбора',
                'style': 'Коротко и по делу',
                'constraints': 'Только локальный контур',
                'assistant_profile': {
                    'tone': 'business',
                    'answer_depth': 'short',
                    'interaction_mode': 'answer_directly',
                    'about_user': 'Второй для bulk update',
                },
            },
        )
        self.assertEqual(second.status_code, 200)
        second_user = second.get_json()['user']

        inactive = self.client.post(
            '/api/admin/users/bulk-status',
            headers=self.auth_headers(token),
            json={'user_ids': [first_user['id'], second_user['id']], 'status': 'inactive'},
        )
        self.assertEqual(inactive.status_code, 200)
        inactive_users = inactive.get_json()['users']
        self.assertEqual(len(inactive_users), 2)
        self.assertTrue(all(user['status'] == 'inactive' for user in inactive_users))
        self.assertTrue(all(user['version'] == 2 for user in inactive_users))

        detail = self.client.get(f'/api/admin/users/{first_user["id"]}', headers=self.auth_headers(token))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()['user']['status'], 'inactive')

        deleted = self.client.post(
            '/api/admin/users/bulk-status',
            headers=self.auth_headers(token),
            json={'user_ids': [second_user['id']], 'status': 'deleted'},
        )
        self.assertEqual(deleted.status_code, 200)
        deleted_user = deleted.get_json()['users'][0]
        self.assertEqual(deleted_user['status'], 'deleted')
        self.assertEqual(deleted_user['version'], 3)

        history = self.client.get(f'/api/admin/users/{second_user["id"]}/history', headers=self.auth_headers(token))
        self.assertEqual(history.status_code, 200)
        history_items = history.get_json()['history']
        self.assertEqual(history_items[0]['change_type'], 'bulk_delete')
        self.assertEqual(history_items[1]['change_type'], 'bulk_inactivate')

    def test_market_share_dashboards_prioritize_pie_and_factor_visuals(self):
        blueprint = self.backend.build_external_dashboard_blueprint('market_overview')
        self.assertIn('pie_list', blueprint['priority_blocks'])
        self.assertIn('pie_list', blueprint['visual_sections'])
        self.assertLess(blueprint['priority_blocks'].index('pie_list'), blueprint['priority_blocks'].index('text_list'))

        payload = self.backend.normalize_external_dashboard_payload(
            {
                'kind': 'external_research_dashboard',
                'title': 'Рынок отечественных ОС',
                'summary_cards': [{'label': 'Период', 'value': '2020–2025'}],
                'sections': [
                    {
                        'kind': 'bar_list',
                        'title': 'Доли рынка по игрокам',
                        'items': [
                            {'label': 'Astra Linux', 'value': '76%', 'ratio': 0.76},
                            {'label': 'РЕД ОС', 'value': '12%', 'ratio': 0.12},
                            {'label': 'Альт', 'value': '10%', 'ratio': 0.10},
                            {'label': 'ОСнова', 'value': '1%', 'ratio': 0.01},
                            {'label': 'РОСА', 'value': '1%', 'ratio': 0.01},
                        ],
                    },
                    {
                        'kind': 'text_list',
                        'title': 'Факторный анализ спроса',
                        'items': [
                            {'text': 'Импортозамещение и регуляторное давление', 'meta': '0.40'},
                            {'text': 'Требования ИБ и сертификация', 'meta': '0.30'},
                            {'text': 'Экосистема внедрения и поддержка', 'meta': '0.20'},
                            {'text': 'Совместимость с отечественным ПО и железом', 'meta': '0.10'},
                        ],
                    },
                ],
                'sources': [{'label': 'Открытые источники'}],
            },
            'Собрала обзор рынка.',
            {'label': 'web_research'},
            {'source_mode': 'global_only'},
            'Проанализируй рынок и построй дашборд по рынку отечественных операционных систем. Нужна динамика с 2020 по 2025 года, доли рынка по топ 5 системам и факторный анализ причин.',
        )
        section_kinds = [section['kind'] for section in payload['sections']]
        self.assertIn('pie_list', section_kinds)
        self.assertIn('bar_list', section_kinds)
        self.assertLess(section_kinds.index('pie_list'), section_kinds.index('text_list'))
        factor_sections = [section for section in payload['sections'] if 'фактор' in section['title'].lower()]
        self.assertTrue(any(section['kind'] in ('bar_list', 'bubble_list', 'pie_list') for section in factor_sections))

    def test_chat_processing_runs_via_background_queue_and_completes(self):
        token = self.login()
        thread_id = self.client.get('/api/threads', headers=self.auth_headers(token)).get_json()['threads'][0]['id']
        original_call = self.backend.call_hermes_api
        original_enabled = self.backend.CHAT_PROCESSOR_ENABLED
        self.backend.CHAT_PROCESSOR_ENABLED = False
        self.backend._chat_processor_stop.set()
        time.sleep(0.05)
        try:
            self.backend.call_hermes_api = lambda rows, profile, thread_title, request_policy=None: ('Фоновый ответ готов.', {'mode': 'test'})
            response = self.client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Запусти фоновую обработку.'},
            )
            self.assertEqual(response.status_code, 201)
            body = response.get_json()
            assistant_message = body['assistant_message']
            task_id = body['chat_task']['id']
            self.assertTrue(assistant_message['meta'].get('pending'))
            self.assertEqual(assistant_message['meta'].get('processing_status'), 'pending')
            self.assertTrue(assistant_message['meta'].get('task_id'))

            before = self.client.get(f'/api/threads/{thread_id}', headers=self.auth_headers(token)).get_json()['messages']
            self.assertTrue(before[-1]['meta'].get('pending'))

            processed = self.backend.process_chat_task(task_id)
            self.assertTrue(processed)

            after = self.client.get(f'/api/threads/{thread_id}', headers=self.auth_headers(token)).get_json()['messages']
            self.assertEqual(after[-1]['content'], 'Фоновый ответ готов.')
            self.assertFalse(after[-1]['meta'].get('pending'))
            self.assertEqual(after[-1]['meta'].get('processing_status'), 'completed')
            with self.backend.db_connect() as conn:
                task_row = conn.execute("SELECT * FROM chat_tasks WHERE id = ?", (task_id,)).fetchone()
                assistant_row = conn.execute("SELECT * FROM messages WHERE id = ?", (assistant_message['id'],)).fetchone()
            self.assertEqual(assistant_row['created_at'], task_row['finished_at'])
        finally:
            self.backend.call_hermes_api = original_call
            self.backend.CHAT_PROCESSOR_ENABLED = original_enabled
            self.backend._chat_processor_stop.clear()

    def test_chat_processing_claim_limit_respects_parallelism_cap(self):
        token = self.login()
        thread_id = self.client.get('/api/threads', headers=self.auth_headers(token)).get_json()['threads'][0]['id']
        original_enabled = self.backend.CHAT_PROCESSOR_ENABLED
        self.backend.CHAT_PROCESSOR_ENABLED = False
        self.backend._chat_processor_stop.set()
        try:
            for index in range(3):
                response = self.client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': f'Фоновая задача {index + 1}'},
                )
                self.assertEqual(response.status_code, 201)
                self.assertTrue(response.get_json()['assistant_message']['meta'].get('pending'))

            claimed = self.backend.claim_pending_chat_tasks(max_tasks=2)
            self.assertEqual(len(claimed), 2)
            with self.backend.db_connect() as conn:
                statuses = conn.execute("SELECT status, COUNT(*) AS c FROM chat_tasks GROUP BY status ORDER BY status").fetchall()
            counts = {row['status']: int(row['c']) for row in statuses}
            self.assertEqual(counts.get('running'), 2)
            self.assertEqual(counts.get('pending'), 1)
        finally:
            self.backend.CHAT_PROCESSOR_ENABLED = original_enabled
            self.backend._chat_processor_stop.clear()

    def test_multiple_users_can_enqueue_requests_in_parallel(self):
        user_emails = ['parallel-a@demo.local', 'parallel-b@demo.local', 'parallel-c@demo.local']
        user_ids = []
        tokens = []
        thread_ids = []
        for email in user_emails:
            user_ids.append(self.create_user(email))
            token = self.login(email)
            tokens.append(token)
            response = self.client.post('/api/threads', headers=self.auth_headers(token), json={'title': f'Чат {email}'})
            self.assertEqual(response.status_code, 201)
            thread_ids.append(response.get_json()['thread']['id'])

        original_enabled = self.backend.CHAT_PROCESSOR_ENABLED
        self.backend.CHAT_PROCESSOR_ENABLED = False
        self.backend._chat_processor_stop.set()
        try:
            def send_message(payload):
                token, thread_id, index = payload
                with self.backend.app.test_client() as client:
                    response = client.post(
                        f'/api/threads/{thread_id}/messages',
                        headers=self.auth_headers(token),
                        json={'content': f'Параллельный запрос {index}'},
                    )
                    body = response.get_json() or {}
                    return response.status_code, body

            with ThreadPoolExecutor(max_workers=3) as pool:
                responses = list(pool.map(send_message, [(tokens[i], thread_ids[i], i + 1) for i in range(3)]))

            for status_code, body in responses:
                self.assertEqual(status_code, 201)
                self.assertTrue(body['assistant_message']['meta'].get('pending'))
                self.assertTrue(body['chat_task']['id'])

            with self.backend.db_connect() as conn:
                rows = conn.execute(
                    "SELECT user_id, status, COUNT(*) AS c FROM chat_tasks WHERE user_id IN (?, ?, ?) GROUP BY user_id, status ORDER BY user_id, status",
                    tuple(user_ids),
                ).fetchall()
            self.assertEqual(sum(int(row['c']) for row in rows if row['status'] == 'pending'), 3)
            self.assertEqual(len({int(row['user_id']) for row in rows}), 3)
        finally:
            self.backend.CHAT_PROCESSOR_ENABLED = original_enabled
            self.backend._chat_processor_stop.clear()

    def test_recover_interrupted_chat_tasks_requeues_running_tasks_after_restart(self):
        token = self.login()
        thread_id = self.client.get('/api/threads', headers=self.auth_headers(token)).get_json()['threads'][0]['id']
        original_enabled = self.backend.CHAT_PROCESSOR_ENABLED
        self.backend.CHAT_PROCESSOR_ENABLED = False
        self.backend._chat_processor_stop.set()
        try:
            response = self.client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Проверь восстановление очереди после перезапуска.'},
            )
            self.assertEqual(response.status_code, 201)
            body = response.get_json()
            task_id = body['chat_task']['id']
            assistant_message_id = body['assistant_message']['id']

            with self.backend.db_connect() as conn:
                baseline_running = conn.execute(
                    "SELECT COUNT(*) AS c FROM chat_tasks WHERE status = 'running' AND finished_at IS NULL"
                ).fetchone()['c']
                conn.execute(
                    "UPDATE chat_tasks SET status = 'running', started_at = ?, last_error = '' WHERE id = ?",
                    (self.backend.now_iso(), task_id),
                )

            recovered = self.backend.recover_interrupted_chat_tasks()
            self.assertGreaterEqual(recovered, baseline_running + 1)

            with self.backend.db_connect() as conn:
                task = conn.execute("SELECT status, started_at, finished_at, last_error FROM chat_tasks WHERE id = ?", (task_id,)).fetchone()
                message = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
            self.assertEqual(task['status'], 'pending')
            self.assertIsNone(task['started_at'])
            self.assertIsNone(task['finished_at'])
            self.assertEqual(task['last_error'], '')
            self.assertEqual(message['content'], 'Готовлю ответ…')
            meta = self.backend.json_loads(message['meta_json'], {})
            self.assertTrue(meta.get('pending'))
            self.assertEqual(meta.get('processing_status'), 'pending')
            self.assertEqual(meta.get('status_label'), 'Восстановлено после перезапуска')
            self.assertEqual(meta.get('task_id'), task_id)
        finally:
            self.backend.CHAT_PROCESSOR_ENABLED = original_enabled
            self.backend._chat_processor_stop.clear()

    def test_route_task_keeps_simple_requests_on_default_model(self):
        with self.backend.db_connect() as conn:
            stats = self.backend.reasoning_usage_stats(conn, 1)
        route = self.backend.route_task('Сделай короткое резюме документа.', 1, stats)
        self.assertEqual(route['model'], self.backend.HERMES_API_MODEL)
        self.assertEqual(route['route_reason'], 'default')
        self.assertIsNone(route['limit_reason'])

    def test_route_task_uses_reasoning_for_explicit_request(self):
        with self.backend.db_connect() as conn:
            stats = self.backend.reasoning_usage_stats(conn, 1)
        route = self.backend.route_task('Сделай глубокий анализ и используй R1 для архитектурных trade-off.', 1, stats)
        self.assertEqual(route['model'], self.backend.HERMES_REASONING_MODEL)
        self.assertEqual(route['route_mode'], 'reasoning')
        self.assertEqual(route['route_reason'], 'explicit_reasoning')

    def test_route_task_falls_back_when_user_reasoning_limit_reached(self):
        user_id = 999
        with self.backend.db_connect() as conn:
            for index in range(self.backend.HERMES_REASONING_DAILY_MAX_PER_USER):
                self.backend.record_llm_usage_event(
                    conn,
                    user_id=user_id,
                    model_key=self.backend.LLM_USAGE_REASONING_MODEL,
                    route_mode='reasoning',
                    route_reason='explicit_reasoning',
                    request_excerpt=f'Запрос {index + 1}',
                    estimated_cost_usd=0.1,
                )
            stats = self.backend.reasoning_usage_stats(conn, user_id)
        route = self.backend.route_task('Используй R1 и сделай глубокий анализ.', user_id, stats)
        self.assertEqual(route['model'], self.backend.HERMES_API_MODEL)
        self.assertEqual(route['route_mode'], 'fallback')
        self.assertEqual(route['limit_reason'], 'user_request_limit')

    def test_route_task_honors_manual_owl_alpha_selection(self):
        with self.backend.db_connect() as conn:
            stats = self.backend.reasoning_usage_stats(conn, 1)
        route = self.backend.route_task('Сделай глубокий анализ.', 1, stats, {'model_preference': 'owl_alpha'})
        self.assertEqual(route['model'], self.backend.HERMES_API_MODEL)
        self.assertEqual(route['route_reason'], 'manual_owl_alpha')
        self.assertIsNone(route['limit_reason'])

    def test_route_task_honors_manual_deepseek_selection(self):
        with self.backend.db_connect() as conn:
            stats = self.backend.reasoning_usage_stats(conn, 1)
        route = self.backend.route_task('Короткий ответ.', 1, stats, {'model_preference': 'deepseek_r1'})
        self.assertEqual(route['model'], self.backend.HERMES_REASONING_MODEL)
        self.assertEqual(route['route_reason'], 'manual_deepseek_r1')
        self.assertIsNone(route['limit_reason'])

    def test_route_task_blocks_manual_deepseek_selection_when_limit_reached(self):
        user_id = 1001
        with self.backend.db_connect() as conn:
            for index in range(self.backend.HERMES_REASONING_DAILY_MAX_PER_USER):
                self.backend.record_llm_usage_event(
                    conn,
                    user_id=user_id,
                    model_key=self.backend.LLM_USAGE_REASONING_MODEL,
                    route_mode='reasoning',
                    route_reason='manual_deepseek_r1',
                    request_excerpt=f'Запрос {index + 1}',
                    estimated_cost_usd=0.1,
                )
            stats = self.backend.reasoning_usage_stats(conn, user_id)
        route = self.backend.route_task('Короткий ответ.', user_id, stats, {'model_preference': 'deepseek_r1'})
        self.assertEqual(route['model'], self.backend.HERMES_API_MODEL)
        self.assertEqual(route['route_reason'], 'manual_deepseek_r1')
        self.assertEqual(route['limit_reason'], 'user_request_limit')

    def test_call_hermes_messages_retries_next_model_on_runtime_error(self):
        original_app_mode = self.backend.APP_MODE
        original_api_key = self.backend.HERMES_API_KEY
        original_candidates = list(self.backend.HERMES_STANDARD_MODEL_CANDIDATES)
        self.backend.APP_MODE = 'hermes-api'
        self.backend.HERMES_API_KEY = 'test-key'
        self.backend.HERMES_STANDARD_MODEL_CANDIDATES = ['model-a', 'model-b']

        class FakeHTTPResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        calls: list[str] = []

        def fake_urlopen(req, timeout=0):
            payload = json.loads(req.data.decode('utf-8'))
            calls.append(payload['model'])
            if payload['model'] == 'model-a':
                raise urllib.error.HTTPError(
                    req.full_url,
                    502,
                    'Bad Gateway',
                    hdrs=None,
                    fp=io.BytesIO(b'{"error_type":"runtime_error","message":"provider returned error"}'),
                )
            return FakeHTTPResponse(json.dumps({
                'model': 'model-b',
                'choices': [{'message': {'content': 'Готово'}}],
                'usage': {'cost_usd': 0.12},
            }).encode('utf-8'))

        try:
            with patch.object(self.backend.urllib.request, 'urlopen', side_effect=fake_urlopen):
                text, meta = self.backend.call_hermes_messages([{'role': 'user', 'content': 'Проверь fallback'}], model_name='model-a')
        finally:
            self.backend.APP_MODE = original_app_mode
            self.backend.HERMES_API_KEY = original_api_key
            self.backend.HERMES_STANDARD_MODEL_CANDIDATES = original_candidates

        self.assertEqual(text, 'Готово')
        self.assertEqual(calls, ['model-a', 'model-b'])
        self.assertTrue(meta['fallback_used'])
        self.assertEqual(meta['requested_model'], 'model-a')
        self.assertEqual(meta['hermes_model'], 'model-b')
        self.assertEqual(meta['model_attempts'][0]['model'], 'model-a')
        self.assertEqual(meta['model_attempts'][0]['status'], 'runtime_error_retry')
        self.assertEqual(meta['model_attempts'][1]['status'], 'success')

    def test_call_hermes_messages_uses_full_timeout_before_last_fallback(self):
        original_app_mode = self.backend.APP_MODE
        original_api_key = self.backend.HERMES_API_KEY
        original_candidates = list(self.backend.HERMES_STANDARD_MODEL_CANDIDATES)
        original_timeout = self.backend.HERMES_API_TIMEOUT
        original_retry_timeout = self.backend.HERMES_API_RETRY_TIMEOUT
        self.backend.APP_MODE = 'hermes-api'
        self.backend.HERMES_API_KEY = 'test-key'
        self.backend.HERMES_STANDARD_MODEL_CANDIDATES = ['model-a', 'model-b']
        self.backend.HERMES_API_TIMEOUT = 180
        self.backend.HERMES_API_RETRY_TIMEOUT = 45

        class FakeHTTPResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        timeouts: list[int] = []

        def fake_urlopen(req, timeout=0):
            payload = json.loads(req.data.decode('utf-8'))
            timeouts.append(timeout)
            if payload['model'] == 'model-a':
                raise urllib.error.HTTPError(
                    req.full_url,
                    502,
                    'Bad Gateway',
                    hdrs=None,
                    fp=io.BytesIO(b'{"error_type":"runtime_error","message":"provider returned error"}'),
                )
            return FakeHTTPResponse(json.dumps({
                'model': 'model-b',
                'choices': [{'message': {'content': 'Готово'}}],
                'usage': {'cost_usd': 0.12},
            }).encode('utf-8'))

        try:
            with patch.object(self.backend.urllib.request, 'urlopen', side_effect=fake_urlopen):
                text, meta = self.backend.call_hermes_messages([{'role': 'user', 'content': 'Проверь timeout'}], model_name='model-a')
        finally:
            self.backend.APP_MODE = original_app_mode
            self.backend.HERMES_API_KEY = original_api_key
            self.backend.HERMES_STANDARD_MODEL_CANDIDATES = original_candidates
            self.backend.HERMES_API_TIMEOUT = original_timeout
            self.backend.HERMES_API_RETRY_TIMEOUT = original_retry_timeout

        self.assertEqual(text, 'Готово')
        self.assertEqual(timeouts, [180, 180])
        self.assertEqual(meta['model_attempts'][0]['timeout_seconds'], 180)
        self.assertEqual(meta['model_attempts'][1]['timeout_seconds'], 180)

    def test_call_hermes_messages_retries_same_model_once_before_fallback_on_timeout(self):
        original_app_mode = self.backend.APP_MODE
        original_api_key = self.backend.HERMES_API_KEY
        original_candidates = list(self.backend.HERMES_STANDARD_MODEL_CANDIDATES)
        original_retry_attempts = self.backend.HERMES_API_TIMEOUT_RETRY_ATTEMPTS
        original_timeout = self.backend.HERMES_API_TIMEOUT
        original_retry_timeout = self.backend.HERMES_API_RETRY_TIMEOUT
        self.backend.APP_MODE = 'hermes-api'
        self.backend.HERMES_API_KEY = 'test-key'
        self.backend.HERMES_STANDARD_MODEL_CANDIDATES = ['model-a', 'model-b']
        self.backend.HERMES_API_TIMEOUT_RETRY_ATTEMPTS = 1
        self.backend.HERMES_API_TIMEOUT = 180
        self.backend.HERMES_API_RETRY_TIMEOUT = 45

        class FakeHTTPResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        calls: list[tuple[str, int]] = []
        model_a_attempts = 0

        def fake_urlopen(req, timeout=0):
            nonlocal model_a_attempts
            payload = json.loads(req.data.decode('utf-8'))
            calls.append((payload['model'], timeout))
            if payload['model'] == 'model-a':
                model_a_attempts += 1
                raise urllib.error.URLError(TimeoutError('timed out'))
            return FakeHTTPResponse(json.dumps({
                'model': 'model-b',
                'choices': [{'message': {'content': 'Готово после timeout fallback'}}],
                'usage': {'cost_usd': 0.12},
            }).encode('utf-8'))

        try:
            with patch.object(self.backend.urllib.request, 'urlopen', side_effect=fake_urlopen):
                text, meta = self.backend.call_hermes_messages([{'role': 'user', 'content': 'Проверь timeout retry'}], model_name='model-a')
        finally:
            self.backend.APP_MODE = original_app_mode
            self.backend.HERMES_API_KEY = original_api_key
            self.backend.HERMES_STANDARD_MODEL_CANDIDATES = original_candidates
            self.backend.HERMES_API_TIMEOUT_RETRY_ATTEMPTS = original_retry_attempts
            self.backend.HERMES_API_TIMEOUT = original_timeout
            self.backend.HERMES_API_RETRY_TIMEOUT = original_retry_timeout

        self.assertEqual(text, 'Готово после timeout fallback')
        self.assertEqual(calls, [('model-a', 180), ('model-a', 45), ('model-b', 180)])
        self.assertTrue(meta['fallback_used'])
        self.assertEqual(meta['model_attempts'][0]['status'], 'timeout_retry_same_model')
        self.assertEqual(meta['model_attempts'][0]['retry_index'], 0)
        self.assertEqual(meta['model_attempts'][1]['status'], 'timeout_retry')
        self.assertEqual(meta['model_attempts'][1]['retry_index'], 1)
        self.assertEqual(meta['model_attempts'][2]['status'], 'success')
        self.assertEqual(meta['model_attempts'][2]['retry_index'], 0)

    def test_finalize_chat_task_error_writes_runtime_audit_event(self):
        with self.backend.db_connect() as conn:
            thread_id = conn.execute(
                "INSERT INTO threads (user_id, title, preview, archived, version, created_at, updated_at) VALUES (1, 'Audit thread', '', FALSE, 1, now(), now()) RETURNING id"
            ).fetchone()[0]
            user_message_id = conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'user', ?, now(), '{}') RETURNING id",
                (thread_id, 'Сломайся красиво'),
            ).fetchone()[0]
            assistant_message_id = conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at, meta_json) VALUES (?, 'assistant', ?, now(), '{}') RETURNING id",
                (thread_id, 'Готовлю ответ…'),
            ).fetchone()[0]
            task_id = conn.execute(
                "INSERT INTO chat_tasks (thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error) VALUES (?, 1, ?, ?, 'running', '{}', now(), now(), NULL, '') RETURNING id",
                (thread_id, user_message_id, assistant_message_id),
            ).fetchone()[0]

        if self.backend.RUNTIME_AUDIT_LOG_PATH.exists():
            self.backend.RUNTIME_AUDIT_LOG_PATH.unlink()
        self.backend.finalize_chat_task_error(task_id, assistant_message_id, 'timed out')

        self.assertTrue(self.backend.RUNTIME_AUDIT_LOG_PATH.exists())
        lines = self.backend.RUNTIME_AUDIT_LOG_PATH.read_text(encoding='utf-8').strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event['event_type'], 'chat_task_error')
        self.assertEqual(event['task_id'], task_id)
        self.assertEqual(event['user_id'], 1)
        self.assertIn('timed out', event['error_text'])

    def test_process_chat_task_logs_degraded_partial_result_event(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Degraded audit thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Собери подборку LegalAI из web'},
                )
            self.assertEqual(response.status_code, 201)
            body = response.get_json()
            task_id = body['chat_task']['id']

        if self.backend.RUNTIME_AUDIT_LOG_PATH.exists():
            self.backend.RUNTIME_AUDIT_LOG_PATH.unlink()

        original_call = self.backend.call_hermes_api
        try:
            self.backend.call_hermes_api = lambda *args, **kwargs: (
                'Частичный результат готов.',
                {
                    'message_kind': 'collection_execution_result',
                    'partial_result': True,
                    'status_note': 'sources_partially_unavailable',
                    'fallback_result_kind': 'hybrid_content_plus_shortlist',
                },
            )
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.call_hermes_api = original_call

        lines = self.backend.RUNTIME_AUDIT_LOG_PATH.read_text(encoding='utf-8').strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event['event_type'], 'chat_task_degraded_result')
        self.assertEqual(event['task_id'], task_id)
        self.assertEqual(event['fallback_result_kind'], 'hybrid_content_plus_shortlist')
        self.assertTrue(event['partial_result'])

    def test_daily_runtime_audit_report_includes_new_classes_and_multi_user_repeats(self):
        module_path = Path(__file__).resolve().parent / 'daily_runtime_audit.py'
        spec = importlib.util.spec_from_file_location('daily_runtime_audit_test_module', module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        window_start = datetime.now(module.UTC) - timedelta(hours=24)
        now = datetime.now(module.UTC)
        events = [
            {
                'event_type': 'chat_task_error',
                'user_id': 1,
                'error_class': 'timed out',
                'public_error_text': 'timed out',
                'request_preview': 'Собери отчёт A',
                'logged_at': '2026-06-24T09:10:00+00:00',
            },
            {
                'event_type': 'chat_task_error',
                'user_id': 2,
                'error_class': 'timed out',
                'public_error_text': 'timed out',
                'request_preview': 'Собери отчёт B',
                'logged_at': '2026-06-24T09:20:00+00:00',
            },
            {
                'event_type': 'chat_task_degraded_result',
                'user_id': 1,
                'fallback_result_kind': 'hybrid_content_plus_shortlist',
                'request_preview': 'Подборка LegalAI',
                'logged_at': '2026-06-24T09:30:00+00:00',
            },
        ]
        users = {1: 'misha@demo.local', 2: 'anna@demo.local'}

        report = module.format_report(events, users, window_start, now)

        self.assertIn('Приоритет на разбор:', report)
        self.assertIn('severity: high=2, medium=1', report)
        self.assertIn('timed out: severity=high, signals=2, users=2, priority=350', report)
        self.assertIn('Новые классы за сутки:', report)
        self.assertIn('hybrid_content_plus_shortlist: severity=medium, signals=1, priority=225', report)
        self.assertIn('Повторяются у нескольких пользователей:', report)
        self.assertIn('timed out: severity=high, signals=2, users=2, priority=350', report)

    def test_process_chat_task_exports_previous_answer_to_file(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Export thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                first_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Первый вопрос'},
                )
            self.assertEqual(first_response.status_code, 201)
            first_body = first_response.get_json()
            first_task_id = first_body['chat_task']['id']

            original_process = self.backend.process_chat_task
            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('Вот основной ответ', {'source': 'test'})
                self.assertTrue(original_process(first_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                export_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Да, лучше сразу в файл'},
                )
            self.assertEqual(export_response.status_code, 201)
            export_body = export_response.get_json()
            export_task_id = export_body['chat_task']['id']
            export_assistant_id = export_body['assistant_message']['id']

        self.assertTrue(self.backend.process_chat_task(export_task_id))
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (export_assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['source'], 'message_export')
        self.assertEqual(meta['export_format'], 'docx')
        self.assertEqual(len(meta['attachments']), 1)
        attachment = meta['attachments'][0]
        self.assertTrue(os.path.exists(attachment['local_path']))
        self.assertTrue(attachment['original_name'].endswith('.docx'))
        self.assertIn('Собрала предыдущий ответ в файл', row['content'])

    def test_process_chat_task_exports_previous_answer_for_generic_file_request(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Generic export thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                first_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Собери стратегический текст про Flatpak'},
                )
            self.assertEqual(first_response.status_code, 201)
            first_body = first_response.get_json()
            first_task_id = first_body['chat_task']['id']

            original_process = self.backend.process_chat_task
            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('Вот стратегический текст про Flatpak', {'source': 'test'})
                self.assertTrue(original_process(first_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                export_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Давай файл'},
                )
            self.assertEqual(export_response.status_code, 201)
            export_body = export_response.get_json()
            export_task_id = export_body['chat_task']['id']
            export_assistant_id = export_body['assistant_message']['id']

        self.assertTrue(self.backend.process_chat_task(export_task_id))
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (export_assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['source'], 'message_export')
        self.assertEqual(meta['export_format'], 'docx')
        self.assertEqual(len(meta['attachments']), 1)
        attachment = meta['attachments'][0]
        self.assertTrue(os.path.exists(attachment['local_path']))
        self.assertTrue(attachment['original_name'].endswith('.docx'))
        self.assertEqual(meta['exported_message_id'], first_body['assistant_message']['id'])
        self.assertIn('Собрала предыдущий ответ в файл', row['content'])

    def test_process_chat_task_exports_previous_answer_for_send_me_file_request(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Send me file thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                first_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Подготовь итоговый текст'},
                )
            self.assertEqual(first_response.status_code, 201)
            first_body = first_response.get_json()
            first_task_id = first_body['chat_task']['id']

            original_process = self.backend.process_chat_task
            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('Вот итоговый текст', {'source': 'test'})
                self.assertTrue(original_process(first_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                export_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Отправь мне файл'},
                )
            self.assertEqual(export_response.status_code, 201)
            export_body = export_response.get_json()
            export_task_id = export_body['chat_task']['id']
            export_assistant_id = export_body['assistant_message']['id']

        self.assertTrue(self.backend.process_chat_task(export_task_id))
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (export_assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['export_format'], 'docx')
        self.assertEqual(meta['exported_message_id'], first_body['assistant_message']['id'])
        self.assertEqual(meta['source'], 'message_export')
        self.assertIn('Собрала предыдущий ответ в файл', row['content'])

    def test_process_chat_task_does_not_misclassify_substantive_xlsx_transformation_as_previous_answer_export(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        user_id = int(user_row['id'])
        request_text = 'Необходимо переделать скрипт объединения данных из разных листов Excel-файла в новый Excel-файл. Старый скрипт: ```import pandas as pd\nprint(1)```'
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            'XLSX transform direct thread',
            [
                ('user', request_text, {'user_text': request_text}),
                ('assistant', '⏳', {'pending': True, 'processing_status': 'pending'}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[0], message_ids[1], '{}', ts),
            )
            task_id = int(cur.fetchone()[0])

        original_call = self.backend.call_hermes_api
        try:
            self.backend.call_hermes_api = lambda *args, **kwargs: ('Ниже обновлённый Python-скрипт для сборки нового Excel-файла.', {'source': 'test'})
            self.assertTrue(self.backend.process_chat_task(task_id))
        finally:
            self.backend.call_hermes_api = original_call

        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (message_ids[1],)).fetchone()
        meta = json.loads(row['meta_json'] or '{}')
        self.assertNotEqual(meta.get('source'), 'message_export')
        self.assertNotEqual(meta.get('message_kind'), 'file_response')
        self.assertIn('обновлённый Python-скрипт', row['content'])

    def test_detect_message_export_format_does_not_trigger_on_docx_filename_only(self):
        self.assertIsNone(self.backend.detect_message_export_format('Проанализируй файл ТЗ2.docx'))
        self.assertIsNone(self.backend.detect_message_export_format('Разбери приложенный документ docx и дай выводы в чат'))
        self.assertEqual(self.backend.detect_message_export_format('Отправь мне файл в docx'), 'docx')
        self.assertEqual(self.backend.detect_message_export_format('А где файл?'), 'docx')

    def test_detect_message_export_format_recognizes_power_point_and_ppt_format_requests(self):
        self.assertEqual(
            self.backend.detect_message_export_format('1) Из интернета 2) Полезную информацию для презентации 3) Результат нужен в виде слайдов Power Point 4) Это должна быть готовая презентация, не таблица'),
            'pptx',
        )
        self.assertTrue(
            self.backend.is_generate_and_attach_file_request('1) Из интернета 2) Полезную информацию для презентации 3) Результат нужен в виде слайдов Power Point 4) Это должна быть готовая презентация, не таблица')
        )
        self.assertEqual(
            self.backend.detect_message_export_format('Подготовить черновик презентации в формате ppt по работе системы мониторинга метрик ИБ'),
            'pptx',
        )
        self.assertTrue(
            self.backend.is_generate_and_attach_file_request('Подготовить черновик презентации в формате ppt по работе системы мониторинга метрик ИБ')
        )

    def test_normalize_memory_items_keeps_only_interaction_rules_and_roles(self):
        items = [
            'Предпочитает короткие ответы по делу',
            'Роль агента — ИТ-архитектор и консультант',
            'Предпочитает CSV с полями: дата, канал, ссылка, summary',
            'Пользователь отслеживает рынок LegalAI и новости в Telegram-каналах',
            'Вместо длинной преамбулы сразу отвечай по сути',
        ]
        self.assertEqual(
            self.backend.normalize_memory_items(items),
            [
                'Предпочитает короткие ответы по делу',
                'Роль агента — ИТ-архитектор и консультант',
                'Вместо длинной преамбулы сразу отвечай по сути',
            ],
        )
        self.assertEqual(self.backend.normalize_memory_items(['Предпочитает еженедельный мониторинг СМИ']), [])
        self.assertEqual(self.backend.normalize_memory_items(['Руководитель направления в Cloud.ru, внедряет промышленные агентные системы на платформе Hermes']), [])
        self.assertEqual(self.backend.normalize_memory_items(['Предпочитает формат дашбордов для структурированного обзора и анализа']), [])
        self.assertEqual(self.backend.sanitize_about_user_text('Роль агента — ИТ-архитектор и консультант'), 'Роль агента — ИТ-архитектор и консультант')
        self.assertEqual(self.backend.sanitize_about_user_text('Пользователь отслеживает рынок LegalAI и новости в Telegram-каналах'), '')

    def test_process_chat_task_exports_previous_answer_for_where_file_followup(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Where file thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                first_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Подготовь итоговый текст по Flatpak'},
                )
            self.assertEqual(first_response.status_code, 201)
            first_body = first_response.get_json()
            first_task_id = first_body['chat_task']['id']

            original_process = self.backend.process_chat_task
            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('Вот итоговый текст по Flatpak', {'source': 'test'})
                self.assertTrue(original_process(first_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                export_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'А где файл?'},
                )
            self.assertEqual(export_response.status_code, 201)
            export_body = export_response.get_json()
            export_task_id = export_body['chat_task']['id']
            export_assistant_id = export_body['assistant_message']['id']

        self.assertTrue(self.backend.process_chat_task(export_task_id))
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (export_assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['export_format'], 'docx')
        self.assertEqual(meta['exported_message_id'], first_body['assistant_message']['id'])
        self.assertIn('Собрала предыдущий ответ в файл', row['content'])

    def test_process_chat_task_exports_previous_answer_for_where_file_followup_without_http(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute(
                "SELECT id FROM users ORDER BY id ASC LIMIT 1"
            ).fetchone()
        user_id = int(user_row['id'])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            'Where file direct thread',
            [
                ('user', 'Подготовь итоговый текст по Flatpak', {'user_text': 'Подготовь итоговый текст по Flatpak'}),
                ('assistant', 'Вот итоговый текст по Flatpak', {'source': 'test'}),
                ('user', 'А где файл?', {'user_text': 'А где файл?'}),
                ('assistant', '⏳', {'pending': True, 'processing_status': 'pending'}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[2], message_ids[3], '{}', ts),
            )
            task_id = int(cur.fetchone()[0])

        self.assertTrue(self.backend.process_chat_task(task_id))
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (message_ids[3],)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['export_format'], 'docx')
        self.assertEqual(meta['exported_message_id'], message_ids[1])
        self.assertIn('Собрала предыдущий ответ в файл', row['content'])

    def test_build_attachment_context_prefers_full_extracted_text_over_preview(self):
        attachment = {
            'original_name': 'ТЗ2.docx',
            'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'size_bytes': 123,
            'text_extracted': True,
            'preview_text': 'ПЕРВЫЕ 10 СИМВОЛОВ',
            'extracted_text': 'ПОЛНЫЙ ТЕКСТ ДОКУМЕНТА\nХВОСТ ДОКУМЕНТА',
            'extraction_note': None,
        }
        context = self.backend.build_attachment_context([attachment])
        self.assertIn('ПОЛНЫЙ ТЕКСТ ДОКУМЕНТА', context)
        self.assertIn('ХВОСТ ДОКУМЕНТА', context)
        self.assertNotIn('ПЕРВЫЕ 10 СИМВОЛОВ\nХВОСТ ДОКУМЕНТА', context)

    def test_process_chat_task_generates_new_content_and_attaches_file_for_substantive_file_request(self):
        if self.backend.pptx is None:
            self.skipTest('python-pptx not installed in current interpreter')
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
                user_id = 1

            thread_id, message_ids = self.create_thread_with_messages(
                user_id,
                'Presentation thread',
                [
                    ('user', 'Дай короткий черновик по Flatpak', {'user_text': 'Дай короткий черновик по Flatpak'}),
                    ('assistant', 'Вот короткий старый черновик', {'source': 'seed'}),
                ],
            )
            seed_assistant_id = message_ids[-1]

            request_response = client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Пришли мне полноценный концепт презентации по Flatpak в виде файла pptx'},
            )
            self.assertEqual(request_response.status_code, 201)
            request_body = request_response.get_json()
            task_id = request_body['chat_task']['id']
            assistant_id = request_body['assistant_message']['id']

            with self.backend.db_connect() as conn:
                conn.execute("UPDATE chat_tasks SET status = 'pending', started_at = NULL, finished_at = NULL, last_error = '' WHERE id = ?", (task_id,))

            original_process = self.backend.process_chat_task
            original_generated_call = self.backend.call_generated_file_content
            try:
                self.backend.call_generated_file_content = lambda *args, **kwargs: ('Новый полноценный концепт презентации по Flatpak', {'source': 'test'})
                original_process(task_id)
                deadline = time.time() + 3
                status = ''
                while time.time() < deadline:
                    with self.backend.db_connect() as conn:
                        row = conn.execute('SELECT status FROM chat_tasks WHERE id = ?', (task_id,)).fetchone()
                    status = row['status'] if row else ''
                    if status == 'completed':
                        break
                    time.sleep(0.05)
                self.assertEqual(status, 'completed')
            finally:
                self.backend.call_generated_file_content = original_generated_call

        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['export_format'], 'pptx')
        self.assertEqual(meta['source'], 'generated_file_response')
        self.assertTrue(meta['generated_from_request'])
        self.assertNotIn('exported_message_id', meta)
        self.assertIn('Собрала новый ответ в файл', row['content'])
        attachment = meta['attachments'][0]
        self.assertTrue(os.path.exists(attachment['local_path']))
        self.assertTrue(attachment['original_name'].endswith('.pptx'))
        self.assertTrue(attachment['preview_excerpt'])
        self.assertNotIn('Вот короткий старый черновик', attachment['preview_excerpt'])
        self.assertNotEqual(seed_assistant_id, assistant_id)

    def test_collection_request_with_url_and_output_details_skips_empty_subject_clarification(self):
        text = (
            'Подбери контакты похожих магазинов по семенам и товарам для дачи и огорода в Адлерском районе Сочи. '
            'Источник: https://2gis.ru/sochi/search/садовый%20центр/rubricId/184107029?m=39.919046%2C43.438483%2F12.55. '
            'Выведи в csv поля: название, адрес, телефон, сайт, часы работы.'
        )
        reply = self.backend.build_collection_clarification_or_contract_reply(text)
        self.assertIsNotNone(reply)
        reply_text, meta = reply
        self.assertEqual(meta['message_kind'], 'collection_contract')
        contract = meta['collection_contract']
        self.assertFalse(contract['missing_fields'])
        self.assertEqual(contract['output_format'], 'csv')
        self.assertGreaterEqual(len(contract['fields']), 4)
        self.assertIn('2gis.ru', ' '.join(contract.get('source_items') or []))
        self.assertIn('Подбери контакты похожих магазинов', contract['subject'])
        self.assertIn('Зафиксировала контракт сбора данных', reply_text)

    def test_process_chat_task_file_request_with_only_limitation_reply_becomes_short_error(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Limitation thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            request_response = client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Отправь мне файл'},
            )
            self.assertEqual(request_response.status_code, 201)
            request_body = request_response.get_json()
            task_id = request_body['chat_task']['id']
            assistant_id = request_body['assistant_message']['id']

            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: (
                    'Я приношу свои извинения. Система безопасности заблокировала запуск команды установки библиотек, поэтому я предоставляю вам финальный текст в формате Markdown ниже.',
                    {'source': 'test'},
                )
                self.assertFalse(self.backend.process_chat_task(task_id))
            finally:
                self.backend.call_hermes_api = original_call

        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertTrue(meta['error'])
        self.assertEqual(meta['processing_status'], 'error')
        self.assertIn('Не удалось сформировать файл', row['content'])
        self.assertNotIn('Markdown', row['content'])

    def test_process_chat_task_generated_file_rejects_tool_transcript_output(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Tool transcript thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            request_response = client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Пришли мне полноценный концепт презентации по Flatpak в виде файла pptx'},
            )
            self.assertEqual(request_response.status_code, 201)
            request_body = request_response.get_json()
            task_id = request_body['chat_task']['id']
            assistant_id = request_body['assistant_message']['id']

            original_messages_call = self.backend.call_hermes_messages
            try:
                self.backend.call_hermes_messages = lambda *args, **kwargs: (
                    'I apologize for the confusion. I encountered an error while attempting to write the file because I missed the required \'path\' parameter.\n\n<tool_code>\nwrite_file(path="_system_prompt.txt", content="You are a helpful assistant.")\n</tool_code>',
                    {'source': 'test'},
                )
                self.assertFalse(self.backend.process_chat_task(task_id))
            finally:
                self.backend.call_hermes_messages = original_messages_call

        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertTrue(meta['error'])
        self.assertEqual(meta['processing_status'], 'error')
        self.assertIn('Не удалось сформировать файл', row['content'])
        self.assertNotIn('tool_code', row['content'])

    def test_process_chat_task_export_skips_service_messages_and_exports_last_content_answer(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Flatpak', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                first_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Расскажи про Flatpak'},
                )
            self.assertEqual(first_response.status_code, 201)
            first_body = first_response.get_json()
            first_task_id = first_body['chat_task']['id']
            first_assistant_id = first_body['assistant_message']['id']

            original_process = self.backend.process_chat_task
            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('Вот содержательный ответ про Flatpak', {'source': 'test'})
                self.assertTrue(original_process(first_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                error_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Проверь ещё раз'},
                )
            self.assertEqual(error_response.status_code, 201)
            error_body = error_response.get_json()
            self.backend.finalize_chat_task_error(
                error_body['chat_task']['id'],
                error_body['assistant_message']['id'],
                'timed out',
            )

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                export_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Лучше сразу в word'},
                )
            self.assertEqual(export_response.status_code, 201)
            export_body = export_response.get_json()
            export_task_id = export_body['chat_task']['id']
            export_assistant_id = export_body['assistant_message']['id']

        self.assertTrue(self.backend.process_chat_task(export_task_id))
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (export_assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['exported_message_id'], first_assistant_id)
        self.assertIn('Вот содержательный ответ про Flatpak', meta['attachments'][0]['preview_excerpt'])
        self.assertNotIn('Не удалось получить ответ', meta['attachments'][0]['preview_excerpt'])

    def test_process_chat_task_export_skips_docx_limitation_apology_and_exports_previous_content_answer(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Flatpak', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                first_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Расскажи про Flatpak'},
                )
            self.assertEqual(first_response.status_code, 201)
            first_body = first_response.get_json()
            first_task_id = first_body['chat_task']['id']
            first_assistant_id = first_body['assistant_message']['id']

            original_process = self.backend.process_chat_task
            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('Вот содержательный ответ про Flatpak', {'source': 'test'})
                self.assertTrue(original_process(first_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                limitation_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'А файл дашь с итоговым вариантом?'},
                )
            self.assertEqual(limitation_response.status_code, 201)
            limitation_body = limitation_response.get_json()
            limitation_task_id = limitation_body['chat_task']['id']
            limitation_assistant_id = limitation_body['assistant_message']['id']

            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: (
                    'Я приношу извинения. Я не могу создавать бинарные файлы .docx и пытался создать текстовые файлы и просто присвоить им расширение.',
                    {'source': 'test'},
                )
                self.assertTrue(original_process(limitation_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True):
                export_response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Так дай файл в docx'},
                )
            self.assertEqual(export_response.status_code, 201)
            export_body = export_response.get_json()
            export_task_id = export_body['chat_task']['id']
            export_assistant_id = export_body['assistant_message']['id']

        self.assertTrue(self.backend.process_chat_task(export_task_id))
        with self.backend.db_connect() as conn:
            exported_row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (export_assistant_id,)).fetchone()
            limitation_row = conn.execute('SELECT content FROM messages WHERE id = ?', (limitation_assistant_id,)).fetchone()
        meta = json.loads(exported_row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['exported_message_id'], first_assistant_id)
        self.assertIn('Вот содержательный ответ про Flatpak', meta['attachments'][0]['preview_excerpt'])
        self.assertNotIn('не могу создавать бинарные файлы', meta['attachments'][0]['preview_excerpt'].lower())
        self.assertIn('не могу создавать бинарные файлы', limitation_row['content'].lower())

    def test_call_hermes_messages_uses_full_timeout_for_all_standard_attempts(self):
        original_app_mode = self.backend.APP_MODE
        original_api_key = self.backend.HERMES_API_KEY
        original_candidates = list(self.backend.HERMES_STANDARD_MODEL_CANDIDATES)
        original_timeout = self.backend.HERMES_API_TIMEOUT
        original_retry_timeout = self.backend.HERMES_API_RETRY_TIMEOUT
        self.backend.APP_MODE = 'hermes-api'
        self.backend.HERMES_API_KEY = 'test-key'
        self.backend.HERMES_STANDARD_MODEL_CANDIDATES = ['model-a', 'model-b']
        self.backend.HERMES_API_TIMEOUT = 180
        self.backend.HERMES_API_RETRY_TIMEOUT = 45

        class FakeHTTPResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        timeouts: list[int] = []

        def fake_urlopen(req, timeout=0):
            payload = json.loads(req.data.decode('utf-8'))
            timeouts.append(timeout)
            if payload['model'] == 'model-a':
                raise urllib.error.HTTPError(
                    req.full_url,
                    502,
                    'Bad Gateway',
                    hdrs=None,
                    fp=io.BytesIO(b'{"error_type":"runtime_error","message":"provider returned error"}'),
                )
            return FakeHTTPResponse(json.dumps({
                'model': 'model-b',
                'choices': [{'message': {'content': 'Готово'}}],
                'usage': {'cost_usd': 0.12},
            }).encode('utf-8'))

        try:
            with patch.object(self.backend.urllib.request, 'urlopen', side_effect=fake_urlopen):
                text, meta = self.backend.call_hermes_messages([{'role': 'user', 'content': 'Проверь timeout'}], model_name='model-a')
        finally:
            self.backend.APP_MODE = original_app_mode
            self.backend.HERMES_API_KEY = original_api_key
            self.backend.HERMES_STANDARD_MODEL_CANDIDATES = original_candidates
            self.backend.HERMES_API_TIMEOUT = original_timeout
            self.backend.HERMES_API_RETRY_TIMEOUT = original_retry_timeout

        self.assertEqual(text, 'Готово')
        self.assertEqual(timeouts, [180, 180])
        self.assertEqual(meta['model_attempts'][0]['timeout_seconds'], 180)
        self.assertEqual(meta['model_attempts'][1]['timeout_seconds'], 180)

    def test_normalize_public_error_text_hides_html(self):
        html_error = '<html><head><title>502</title></head><body>bad gateway</body></html>'
        self.assertEqual(
            self.backend.normalize_public_error_text(html_error),
            'Ошибка runtime: вместо API-ответа вернулась HTML-страница.'
        )

    def test_normalize_public_error_text_hides_escaped_html(self):
        html_error = '⚠️ &lt;html&gt;&lt;head&gt;<meta name="viewport" content="width=device-width" />&lt;/head&gt;&lt;body&gt;bad gateway&lt;/body&gt;&lt;/html&gt;'
        self.assertEqual(
            self.backend.normalize_public_error_text(html_error),
            'Ошибка runtime: вместо API-ответа вернулась HTML-страница.'
        )

    def test_normalize_public_error_text_hides_overlong_error(self):
        long_error = 'x' * 700
        self.assertEqual(
            self.backend.normalize_public_error_text(long_error),
            'Ошибка runtime: источник вернул слишком длинную техническую ошибку.'
        )

    def test_finalize_chat_task_error_uses_public_error_text(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Test thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']
            user_message = client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Проверь ошибку'},
            )
            self.assertEqual(user_message.status_code, 201)
            body = user_message.get_json()
            assistant_message_id = body['assistant_message']['id']
            task_id = body['chat_task']['id']
        self.backend.finalize_chat_task_error(task_id, assistant_message_id, '<html><body>boom</body></html>')
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT meta_json FROM messages WHERE id = ?', (assistant_message_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['error_text'], 'Ошибка runtime: вместо API-ответа вернулась HTML-страница.')
        self.assertTrue(meta['internal_error_stored'])
        self.assertNotIn('raw_error_text', meta)

    def test_bootstrap_exposes_llm_routing_selector(self):

        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            response = client.get('/api/bootstrap', headers={'Authorization': f'Bearer {token}'})
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
        selector = payload['llm_routing']['selector']
        self.assertEqual(selector['default'], 'auto')
        self.assertEqual([item['value'] for item in selector['options']], ['auto', 'owl_alpha', 'deepseek_r1'])

    def test_seed_reference_data_refreshes_job_template_fields(self):
        with self.backend.db_connect() as conn:
            conn.execute(
                "UPDATE reference_items SET label = ?, payload_json = ? WHERE dataset_key = ? AND item_key = ?",
                (
                    'Мониторинг темы',
                    self.backend.json.dumps({
                        'description': 'Повторяющийся обзор темы с фокусом на полезные сигналы.',
                        'fields': [
                            {'key': 'subject', 'label': 'Тема мониторинга', 'type': 'text', 'placeholder': 'Например: LegalAI, multi-agent, Telegram'},
                            {'key': 'angle', 'label': 'Угол обзора', 'type': 'text', 'placeholder': 'Рынок, архитектура, конкуренты, риски'},
                            {'key': 'output', 'label': 'Форма результата', 'type': 'text', 'placeholder': 'Короткий дайджест, выводы, список действий'},
                        ],
                    }, ensure_ascii=False),
                    self.backend.REFERENCE_DATASET_JOB_TEMPLATES,
                    'research_watch',
                ),
            )
            self.backend.seed_reference_data(conn)
            refreshed = conn.execute(
                "SELECT payload_json FROM reference_items WHERE dataset_key = ? AND item_key = ?",
                (self.backend.REFERENCE_DATASET_JOB_TEMPLATES, 'research_watch'),
            ).fetchone()
        payload = self.backend.json_loads(refreshed['payload_json'], {})
        fields = payload.get('fields') or []
        angle_field = next(field for field in fields if field.get('key') == 'angle')
        output_field = next(field for field in fields if field.get('key') == 'output')
        self.assertEqual(angle_field['label'], 'Состав обзора')
        self.assertEqual(angle_field['type'], 'textarea')
        self.assertEqual(angle_field['rows'], 5)
        self.assertEqual(output_field['label'], 'Формат результата')

    def test_session_ttl_defaults_to_one_hour(self):
        self.assertEqual(self.backend.SESSION_TTL_HOURS, 1)
        expires_at = self.backend.session_expires_at('2026-06-16T10:00:00+00:00')
        self.assertEqual(expires_at.isoformat(), '2026-06-16T11:00:00+00:00')

    def test_authorized_request_touches_session_by_default(self):
        stale_seen = self.backend.now_iso(self.backend.now_utc() - timedelta(seconds=self.backend.SESSION_TOUCH_INTERVAL_SECONDS + 5))
        with self.backend.db_connect() as conn:
            token = self.backend.issue_session(conn, 1)
            conn.execute('UPDATE sessions SET last_seen_at = ? WHERE token = ?', (stale_seen, token))
        with self.backend.app.test_client() as client:
            response = client.get('/api/me', headers=self.auth_headers(token))
            self.assertEqual(response.status_code, 200)
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT last_seen_at FROM sessions WHERE token = ?', (token,)).fetchone()
        self.assertNotEqual(row['last_seen_at'], stale_seen)

    def test_extract_docx_text_includes_tables_and_header(self):
        if self.backend.docx is None:
            self.skipTest('python-docx not installed')
        doc_path = Path(self.tempdir) / 'extract-rich.docx'
        document = self.backend.docx.Document()
        section = document.sections[0]
        section.header.paragraphs[0].text = 'Header line'
        document.add_paragraph('Body line')
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = 'A1'
        table.cell(0, 1).text = 'B1'
        table.cell(1, 0).text = 'A2'
        table.cell(1, 1).text = 'B2'
        document.save(doc_path)
        text, note = self.backend.extract_text_from_path(doc_path, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertIsNone(note)
        self.assertIn('Header line', text)
        self.assertIn('Body line', text)
        self.assertIn('A1 | B1', text)
        self.assertIn('A2 | B2', text)

    def test_extract_xlsx_text_reads_sheet_rows(self):
        if self.backend.openpyxl is None:
            self.skipTest('openpyxl not installed')
        xlsx_path = Path(self.tempdir) / 'extract-rich.xlsx'
        workbook = self.backend.openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = 'ТЗ'
        sheet.append(['Раздел', 'Значение'])
        sheet.append(['Scope', 'Backend'])
        workbook.save(xlsx_path)
        text, note = self.backend.extract_text_from_path(xlsx_path, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIsNone(note)
        self.assertIn('[Лист: ТЗ]', text)
        self.assertIn('Раздел | Значение', text)
        self.assertIn('Scope | Backend', text)

    def test_process_chat_task_blocks_generic_llm_failure_output(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Generic guard thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']
            request_response = client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Ответь нормально без мусора'},
            )
            self.assertEqual(request_response.status_code, 201)
            body = request_response.get_json()
            task_id = body['chat_task']['id']
            assistant_id = body['assistant_message']['id']
            original_call = self.backend.call_hermes_api
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('<tool_code>\nwrite_file(path="x", content="boom")\n</tool_code>', {'source': 'test'})
                self.assertFalse(self.backend.process_chat_task(task_id))
            finally:
                self.backend.call_hermes_api = original_call
        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertTrue(meta['error'])
        self.assertEqual(meta['processing_status'], 'error')
        self.assertIn('Не удалось получить ответ', row['content'])

    def test_extract_pptx_text_returns_dependency_note_when_library_missing(self):
        if self.backend.pptx is not None:
            self.skipTest('python-pptx installed; dependency-missing path not applicable')
        pptx_path = Path(self.tempdir) / 'deck.pptx'
        pptx_path.write_bytes(b'fake-pptx')
        text, note = self.backend.extract_text_from_path(
            pptx_path,
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        )
        self.assertEqual(text, '')
        self.assertIn('python-pptx', note)

    def test_extract_pptx_text_reads_shapes_tables_and_notes(self):
        if self.backend.pptx is None:
            self.skipTest('python-pptx not installed')
        pptx_path = Path(self.tempdir) / 'extract-rich.pptx'
        presentation = self.backend.pptx.Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        textbox = slide.shapes.add_textbox(left=0, top=0, width=3000000, height=500000)
        textbox.text_frame.text = 'Main title'
        table_shape = slide.shapes.add_table(2, 2, 0, 600000, 4000000, 1200000)
        table = table_shape.table
        table.cell(0, 0).text = 'A1'
        table.cell(0, 1).text = 'B1'
        table.cell(1, 0).text = 'A2'
        table.cell(1, 1).text = 'B2'
        notes_text_frame = slide.notes_slide.notes_text_frame
        notes_text_frame.text = 'Speaker note'
        presentation.save(pptx_path)
        text, note = self.backend.extract_text_from_path(
            pptx_path,
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        )
        self.assertIsNone(note)
        self.assertIn('[Слайд 1]', text)
        self.assertIn('Main title', text)
        self.assertIn('A1 | B1', text)
        self.assertIn('A2 | B2', text)
        self.assertIn('Speaker note', text)

    def test_should_compact_chat_history_when_char_budget_exceeded(self):
        messages = [
            {'role': 'system', 'content': 'system'},
            {'role': 'user', 'content': 'x' * (self.backend.CHAT_CONTEXT_CHAR_BUDGET + 5)},
        ]
        self.assertTrue(self.backend.should_compact_chat_history(messages))

    def test_call_hermes_api_compacts_long_standard_history(self):
        base_messages = [{'role': 'system', 'content': 'system prompt'}]
        for index in range(self.backend.CHAT_CONTEXT_SUMMARY_TRIGGER_MESSAGES + 3):
            role = 'user' if index % 2 == 0 else 'assistant'
            base_messages.append({'role': role, 'content': f'message-{index} ' + ('x' * 50)})
        original_build = self.backend.build_hermes_messages
        original_route = self.backend.route_task
        original_call = self.backend.call_hermes_messages
        try:
            self.backend.build_hermes_messages = lambda *args, **kwargs: list(base_messages)
            self.backend.route_task = lambda *args, **kwargs: {'model': 'standard-model', 'route_mode': 'standard', 'route_reason': 'test'}
            seen_payloads = []
            def fake_call(messages, model_name=None, timeout=None):
                seen_payloads.append(messages)
                if len(seen_payloads) == 1:
                    return ('summary of older chat', {'hermes_model': 'summary-model'})
                return ('final answer', {'hermes_model': 'standard-model'})
            self.backend.call_hermes_messages = fake_call
            reply_text, meta = self.backend.call_hermes_api([], {'id': 1, 'assistant_profile': {'tone': '', 'answer_depth': '', 'interaction_mode': ''}, 'name': '', 'title': '', 'team': '', 'language': 'ru', 'timezone': 'UTC', 'goals': '', 'constraints': '', 'pinned': []}, 'Thread', None)
        finally:
            self.backend.build_hermes_messages = original_build
            self.backend.route_task = original_route
            self.backend.call_hermes_messages = original_call
        self.assertEqual(reply_text, 'final answer')
        self.assertTrue(meta['history_compacted'])
        self.assertEqual(meta['history_summary_model'], 'summary-model')
        self.assertEqual(len(seen_payloads), 2)
        final_messages = seen_payloads[-1]
        self.assertEqual(final_messages[1]['role'], 'system')
        self.assertIn('Сводка предыдущей части этого же чата', final_messages[1]['content'])

    def test_is_dashboard_request_requires_explicit_dashboard_intent(self):
        self.assertFalse(self.backend.is_dashboard_request(
            'Проверь общую текстовку письма: в тексте есть Telegram, интернет и глубокая аналитика, но задача — просто отредактировать письмо.'
        ))
        self.assertTrue(self.backend.is_dashboard_request(
            'Построй дашборд по основным трендам, вопросам, кейсам и потенциальной аудитории каналов.'
        ))

    def test_postprocess_assistant_reply_strips_non_executable_action_promises_for_generic_chat(self):
        reply = (
            'Да, это возможно.\n\n'
            '**Что я сделаю сейчас:**\n'
            '1. Проверю наличие рабочей директории и текущее состояние сессии.\n'
            '2. Создам файл конфигурации с вашим списком вендоров и интеграторов.\n'
            '3. Запущу выгрузку данных.\n\n'
            'Приступаю к проверке инфраструктуры.'
        )
        cleaned = self.backend.postprocess_assistant_reply(
            'У тебя есть доступ к коннектору TG API. Проверь возможность создания отдельного списка каналов для него',
            reply,
            {'downstream': 'hermes-api-server'},
        )
        self.assertEqual(cleaned, 'Да, это возможно.')

    def test_short_followup_confirmation_detection(self):
        self.assertTrue(self.backend.is_short_followup_confirmation('Да, сделай'))
        self.assertTrue(self.backend.is_short_followup_confirmation('запускай'))
        self.assertFalse(self.backend.is_short_followup_confirmation('Сделай отдельный список каналов TG API и сохрани его в новый конфиг-файл'))

    def test_short_problem_followup_detection(self):
        self.assertTrue(self.backend.is_short_problem_followup('Не работает'))
        self.assertTrue(self.backend.is_short_problem_followup('А где файл?'))
        self.assertTrue(self.backend.is_short_problem_followup('Непонятно, повтори ещё раз'))
        self.assertFalse(self.backend.is_short_problem_followup('Сделай отдельный CSV со списком подрядчиков и оцени стоимость'))

    def test_should_use_focused_followup_context_for_long_assistant_plan(self):
        rows = [
            {'role': 'user', 'content': 'Проверь возможность создания отдельного списка каналов для TG API'},
            {'role': 'assistant', 'content': 'План. ' + ('Шаг. ' * 80)},
            {'role': 'user', 'content': 'Да, сделай'},
        ]
        self.assertTrue(self.backend.should_use_focused_followup_context(rows, {}))
        self.assertIn('План.', self.backend.latest_substantive_assistant_message_text(rows[:-1]))

    def test_should_use_focused_followup_context_for_short_problem_reply(self):
        rows = [
            {'role': 'user', 'content': 'Собери файл по предыдущему ответу'},
            {'role': 'assistant', 'content': 'Готово. ' + ('Файл будет приложен. ' * 20)},
            {'role': 'user', 'content': 'А где файл?'},
        ]
        self.assertTrue(self.backend.should_use_focused_followup_context(rows, {}))

    def test_should_use_focused_followup_context_for_problem_reply_after_short_answer(self):
        rows = [
            {'role': 'user', 'content': 'Подготовь короткий план запуска weekly monitoring'},
            {'role': 'assistant', 'content': 'Сделай три шага: выбери тему, задай расписание, проверь доставку в чат.'},
            {'role': 'user', 'content': 'не работает'},
        ]
        self.assertTrue(self.backend.should_use_focused_followup_context(rows, {}))
        self.assertTrue(self.backend.should_use_focused_followup_context(rows, {'source_mode': '', 'model_preference': 'auto', 'explicit_source_ids': [], 'allowed_source_ids': [], 'connector_targets': {}}))

    def test_normalize_public_error_text_timeout_is_generic_not_file_specific(self):
        text = self.backend.normalize_public_error_text('timed out')
        self.assertIn('Не удалось получить ответ', text)
        self.assertNotIn('сформировать файл', text)

    def test_reply_violates_expected_language_for_russian_profile(self):
        profile = {'language': 'ru'}
        self.assertTrue(self.backend.reply_violates_expected_language('Based on the search results, here is the information.', profile))
        self.assertTrue(self.backend.reply_violates_expected_language('uma resposta detalhada e estruturada, sem enrolação', profile))
        self.assertFalse(self.backend.reply_violates_expected_language('Собрала краткий вывод и следующий шаг.', profile))

    def test_build_generated_file_reply_rejects_fake_structured_exports(self):
        with self.assertRaises(self.backend.ApiError) as cm:
            self.backend.build_generated_file_reply(
                assistant_message_id=1,
                reply_text='обычный текст ответа',
                reply_meta={},
                thread_title='Тест',
                export_format='csv',
                created_at=self.backend.now_iso(),
            )
        self.assertEqual(cm.exception.message, 'structured_generated_file_not_supported')

    def test_recurring_job_detection_catches_weekly_media_collection(self):
        self.assertTrue(self.backend.looks_like_recurring_job_request('Поставь еженедельный сбор информации из СМИ в чате.'))
        self.assertTrue(self.backend.looks_like_recurring_job_followup('Да, давай поставь еженедельный обзор новостей по этой теме.'))

    def test_collection_request_without_source_and_fields_returns_clarification(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Сбор данных",
            [
                ("user", "Собери данные по LegalAI в csv", {"user_text": "Собери данные по LegalAI в csv"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        user_message_id = message_ids[0]
        assistant_message_id = message_ids[1]
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, user_message_id, assistant_message_id, "{}", ts),
            )
            task_id = int(cur.fetchone()[0])
        processed = self.backend.process_chat_task(task_id)
        self.assertTrue(processed)
        with self.backend.db_connect() as conn:
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
        meta = json.loads(assistant["meta_json"] or "{}")
        self.assertEqual(meta.get("message_kind"), "clarification_request")
        self.assertEqual(meta.get("downstream"), "chat:data_collection_clarification")
        self.assertIn("контракт сбора", assistant["content"])
        contract = meta.get("collection_contract") or {}
        self.assertIn("источник", contract.get("missing_fields") or [])
        self.assertIn("поля / колонки результата", contract.get("missing_fields") or [])

    def test_collection_request_with_source_format_and_fields_returns_contract(self):
        text = "Собери данные из СМИ по теме LegalAI в csv с полями дата, источник, ссылка, summary"
        reply = self.backend.build_collection_clarification_or_contract_reply(text, None)
        self.assertIsNotNone(reply)
        reply_text, meta = reply
        self.assertEqual(meta.get("message_kind"), "collection_contract")
        self.assertEqual(meta.get("downstream"), "chat:data_collection_contract")
        self.assertIn("Живой алгоритм выполнения", reply_text)
        contract = meta.get("collection_contract") or {}
        self.assertEqual(contract.get("source_kind"), "media")
        self.assertEqual(contract.get("output_format"), "csv")
        self.assertEqual(contract.get("subject"), "LegalAI")
        self.assertEqual(contract.get("fields"), ["дата", "источник", "ссылка", "summary"])
        self.assertEqual(contract.get("missing_fields"), [])



    def test_collection_request_with_real_tender_prompt_returns_contract(self):
        text = """Мне нужно, чтобы ты настроил выгрузку данных с тендерных площадок (указанных выше). Нужны данные в формате excel (csv). Данные нужны по закупкам в части ИТ-деятельности. Нужны все закупки с 01.06.2026.
Нужна информация:

Заказчик (кто является инициатором или для кого делается процедура)
Стоимость
Срок размещения
Срок подачи
Город поставки
Объект закупки
Ссылка на закупку
Различные комментарии, которые есть к закупке, которые позволяют уточнить.
Источники - bidzaar.com/, roseltorg.ru/, fabrikant.ru, b2b-center.ru, etp.gpb.ru, zakupki.mos.ru, zakupki.gov.ru"""
        reply = self.backend.build_collection_clarification_or_contract_reply(text, None)
        self.assertIsNotNone(reply)
        reply_text, meta = reply
        self.assertEqual(meta.get("message_kind"), "collection_contract")
        self.assertEqual(meta.get("downstream"), "chat:data_collection_contract")
        contract = meta.get("collection_contract") or {}
        self.assertEqual(contract.get("source_kind"), "tenders")
        self.assertEqual(contract.get("output_format"), "csv")
        self.assertEqual(contract.get("subject"), "ИТ-деятельности")
        self.assertEqual(contract.get("missing_fields"), [])
        self.assertEqual(
            contract.get("fields"),
            [
                "Заказчик (кто является инициатором или для кого делается процедура)",
                "Стоимость",
                "Срок размещения",
                "Срок подачи",
                "Город поставки",
                "Объект закупки",
                "Ссылка на закупку",
                "Различные комментарии, которые есть к закупке, которые позволяют уточнить",
            ],
        )
        self.assertIn("Источник:", reply_text)

    def test_maybe_execute_collection_request_runs_telegram_api_with_task_channel_list(self):
        text = "Собери данные из Telegram-каналов @legal_ai_news, @robotics_digest в csv с полями дата, канал, ссылка, summary с 01.06.2026"
        contract = self.backend.build_collection_contract_meta(text, None)
        tg_dir = Path(self.tempdir) / "tg-api"
        tg_dir.mkdir(parents=True, exist_ok=True)
        os.environ["TG_API_CONFIG_DIR"] = str(tg_dir)
        with patch.object(self.backend.urllib.request, "urlopen") as mocked_urlopen:
            response_mock = mocked_urlopen.return_value.__enter__.return_value
            response_mock.status = 200
            response_mock.read.return_value = json.dumps({
                "count": 12,
                "profile": "profile_1",
                "config": "demo",
                "messages": [
                    {
                        "id": 101,
                        "date": "2026-06-01T10:00:00+00:00",
                        "chat": "legal_ai_news",
                        "message": "Legal AI update",
                        "original_url": "https://t.me/legal_ai_news/101"
                    }
                ],
            }, ensure_ascii=False).encode("utf-8")
            reply_text, meta = self.backend.execute_telegram_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        self.assertEqual(meta.get("downstream"), "chat:telegram_collection_result")
        source_list = meta.get("task_source_list") or {}
        self.assertEqual(source_list.get("kind"), "telegram_channels")
        self.assertTrue(Path(source_list.get("config_path")).exists())
        config_text = Path(source_list.get("config_path")).read_text(encoding="utf-8")
        self.assertIn("legal_ai_news", config_text)
        self.assertIn("robotics_digest", config_text)
        self.assertIn("Сообщений получено: 12", reply_text)
        attachments = meta.get("attachments") or []
        self.assertEqual(len(attachments), 1)
        attachment = attachments[0]
        self.assertTrue(Path(attachment.get("local_path")).exists())
        csv_text = Path(attachment.get("local_path")).read_text(encoding="utf-8")
        self.assertIn("дата,канал,ссылка,summary,source_url", csv_text)
        self.assertIn("legal_ai_news", csv_text)
        execution_lock = meta.get("execution_lock") or {}
        self.assertEqual(execution_lock.get("kind"), "telegram_collection_singleflight")

    def test_execute_telegram_collection_contract_waits_for_singleflight_lock(self):
        text = "Собери данные из Telegram-каналов @legal_ai_news в csv с полями дата, канал, ссылка, summary с 01.06.2026"
        contract = self.backend.build_collection_contract_meta(text, None)
        tg_dir = Path(self.tempdir) / "tg-api-lock"
        tg_dir.mkdir(parents=True, exist_ok=True)
        os.environ["TG_API_CONFIG_DIR"] = str(tg_dir)
        original_timeout = self.backend.TELEGRAM_COLLECTION_LOCK_TIMEOUT
        original_lock = self.backend._telegram_collection_lock
        self.backend.TELEGRAM_COLLECTION_LOCK_TIMEOUT = 5
        self.backend._telegram_collection_lock = threading.Lock()
        entered = threading.Event()
        result: dict[str, object] = {}

        def fake_urlopen(*args, **kwargs):
            entered.set()
            class _Resp:
                status = 200
                def __enter__(self_inner):
                    return self_inner
                def __exit__(self_inner, exc_type, exc, tb):
                    return False
                def read(self_inner):
                    return b'{"count": 3, "profile": "profile_1", "config": "demo"}'
            return _Resp()

        def worker():
            try:
                reply_text, meta = self.backend.execute_telegram_collection_contract(contract)
                result["reply_text"] = reply_text
                result["meta"] = meta
            except Exception as exc:  # pragma: no cover
                result["error"] = exc

        try:
            self.backend._telegram_collection_lock.acquire()
            with patch.object(self.backend.urllib.request, "urlopen", side_effect=fake_urlopen):
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                thread.join(0.2)
                self.assertFalse(entered.is_set())
                self.backend._telegram_collection_lock.release()
                thread.join(2)
        finally:
            if self.backend._telegram_collection_lock.locked():
                self.backend._telegram_collection_lock.release()
            self.backend._telegram_collection_lock = original_lock
            self.backend.TELEGRAM_COLLECTION_LOCK_TIMEOUT = original_timeout

        self.assertNotIn("error", result)
        self.assertTrue(entered.is_set())
        execution_lock = (result.get("meta") or {}).get("execution_lock") or {}
        self.assertEqual(execution_lock.get("kind"), "telegram_collection_singleflight")
        self.assertGreaterEqual(float(execution_lock.get("wait_seconds") or 0.0), 0.0)

    def test_normalize_public_error_text_for_telegram_busy_timeout(self):
        text = self.backend.normalize_public_error_text('telegram_collection_busy_timeout')
        self.assertIn('Telegram-выгрузка ещё занята', text)

    def test_tender_prompt_with_setup_wording_is_still_collection_request(self):
        text = "Мне нужно, чтобы ты настроил выгрузку данных с тендерных площадок в csv по закупкам в части ИТ-деятельности с 01.06.2026"
        self.assertTrue(self.backend.looks_like_collection_request(text))
        contract = self.backend.build_collection_contract_meta(text, None)
        self.assertEqual(contract.get("source_kind"), "tenders")
        self.assertEqual(contract.get("output_format"), "csv")
        self.assertEqual(contract.get("since_date"), "2026-06-01")

        text = """Мне нужно, чтобы ты настроил выгрузку данных с тендерных площадок. Нужны данные в формате csv по закупкам в части ИТ-деятельности с 01.06.2026.
Нужна информация:
Заказчик
Стоимость
Срок подачи
Ссылка на закупку
Источники - bidzaar.com, roseltorg.ru, fabrikant.ru, b2b-center.ru, zakupki.gov.ru"""
        contract = self.backend.build_collection_contract_meta(text, None)
        fake_dir = Path(self.backend.DATA_DIR) / "test-tender-run"
        fake_dir.mkdir(parents=True, exist_ok=True)
        csv_path = fake_dir / "it_tenders_2026-06-01.csv"
        status_path = fake_dir / "tender_sources_status_2026-06-01.csv"
        csv_path.write_text("кто;что\nA;B\n", encoding="utf-8")
        status_path.write_text("источник;статус\nzakupki.gov.ru;собрано\n", encoding="utf-8")
        with patch.object(self.backend, "run_tender_pipeline_snapshot", return_value={
            "target_date": "01.06.2026",
            "run_dir": str(fake_dir),
            "summary_path": str(fake_dir / "last_run_summary.json"),
            "summary": {"total_rows": 1, "by_source": {"zakupki.gov.ru": 1}, "status_by_source": {"zakupki.gov.ru": "собрано"}},
            "csv_attachment": self.backend.build_existing_file_attachment(str(csv_path), source="tender_pipeline"),
            "status_attachment": self.backend.build_existing_file_attachment(str(status_path), kind="collection_status_artifact", source="tender_pipeline"),
        }):
            reply_text, meta = self.backend.execute_tender_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        self.assertEqual(meta.get("downstream"), "chat:tender_collection_result")
        source_list = meta.get("task_source_list") or {}
        self.assertEqual(source_list.get("kind"), "tender_sources")
        self.assertTrue(Path(source_list.get("path")).exists())
        payload = json.loads(Path(source_list.get("path")).read_text(encoding="utf-8"))
        self.assertIn("zakupki.gov.ru", payload.get("requested_sources") or [])
        attachments = meta.get("attachments") or []
        self.assertEqual(len(attachments), 2)
        self.assertTrue(Path(attachments[0].get("local_path")).exists())
        self.assertIn("Файл выгрузки", reply_text)

    def test_execute_web_collection_contract_creates_real_csv_artifact(self):
        text = "Собери данные с https://example.org и https://example.com в csv по теме test dataset с полями title, summary"
        contract = self.backend.build_collection_contract_meta(text, None)
        documents = [
            {
                "requested_url": "https://example.org",
                "final_url": "https://example.org",
                "title": "Example Org",
                "text": "Example Org text about test dataset history and dataset details.",
            },
            {
                "requested_url": "https://example.com",
                "final_url": "https://example.com",
                "title": "Example Com",
                "text": "Example Com text about test dataset details and dataset summary.",
            },
        ]
        with patch.object(self.backend, "fetch_web_source_document", side_effect=documents), patch.object(
            self.backend,
            "call_hermes_messages",
            return_value=(json.dumps({"rows": [
                {"source_url": "https://example.org", "title": "Example Org", "summary": "history"},
                {"source_url": "https://example.com", "title": "Example Com", "summary": "details"},
            ]}, ensure_ascii=False), {}),
        ):
            reply_text, meta = self.backend.execute_web_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        self.assertEqual(meta.get("downstream"), "chat:web_collection_result")
        attachments = meta.get("attachments") or []
        self.assertEqual(len(attachments), 1)
        attachment = attachments[0]
        csv_text = Path(attachment["local_path"]).read_text(encoding="utf-8")
        self.assertIn("Example Org", csv_text)
        self.assertIn("Файл:", reply_text)

    def test_select_relevant_web_documents_keeps_soft_match_documents_for_subject_queries(self):
        contract = {
            "subject": "HR-тренды",
            "request_text": "Собери данные из интернета по HR-трендам",
            "source_kind": "web",
            "fields": ["title", "summary"],
        }
        documents = [
            {
                "requested_url": "https://example.com/hr1",
                "final_url": "https://example.com/hr1",
                "title": "Тренды найма и удержания персонала",
                "text": "В материале обсуждаются практики найма, компенсации, удержание сотрудников и изменения рынка труда.",
            },
            {
                "requested_url": "https://example.com/hr2",
                "final_url": "https://example.com/hr2",
                "title": "Изменения рынка труда",
                "text": "Компании меняют подход к рекрутингу, используют ИИ в HR и перестраивают политику найма.",
            },
        ]
        selected = self.backend.select_relevant_web_documents(contract, documents)
        self.assertGreaterEqual(len(selected), 1)
        self.assertIn(selected[0]["final_url"], {"https://example.com/hr1", "https://example.com/hr2"})

    def test_fetch_web_source_document_retries_once_after_403(self):
        class FakeResponse:
            def __init__(self, body: bytes, url: str, content_type: str = "text/html; charset=utf-8"):
                self._body = body
                self.url = url
                self.headers = {"Content-Type": content_type}
            def read(self, _size: int = -1):
                return self._body
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False

        calls = []
        def fake_urlopen(request, timeout=40):
            calls.append(dict(request.header_items()))
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)
            return FakeResponse("<html><head><title>HR Trends</title></head><body>рынок труда и hr trends</body></html>".encode("utf-8"), request.full_url)

        with patch.object(self.backend.urllib.request, "urlopen", side_effect=fake_urlopen):
            doc = self.backend.fetch_web_source_document("https://example.com/hr")

        self.assertEqual(doc["final_url"], "https://example.com/hr")
        self.assertIn("HR Trends", doc["title"])
        self.assertEqual(len(calls), 2)
        second_headers = {str(k).lower(): v for k, v in calls[1].items()}
        self.assertIn("accept-language", second_headers)

    def test_execute_web_collection_contract_returns_dashboard_result_for_dashboard_output(self):
        text = "Собери данные из интернета по теме LegalAI и построй дашборд с полями компания, type, summary"
        contract = self.backend.build_collection_contract_meta(text, None)
        self.assertEqual(contract.get("subject"), "LegalAI")
        self.assertEqual(contract.get("output_format"), "dashboard")
        self.assertEqual(contract.get("source_kind"), "web")
        self.assertFalse(contract.get("missing_fields"))

        market_text = "Собери из интернета данные по рынку LegalAI и дай дашборд."
        market_contract = self.backend.build_collection_contract_meta(market_text, None)
        self.assertEqual(market_contract.get("subject"), "LegalAI")
        self.assertEqual(market_contract.get("output_format"), "dashboard")
        self.assertEqual(market_contract.get("source_kind"), "web")
        self.assertFalse(market_contract.get("missing_fields"))

    def test_market_dashboard_request_defaults_to_web_research_without_contract_intake(self):
        text = "Проанализируй рынок автомобилей geely в России в 2024-2025 годах и построй дашборд"
        contract = self.backend.build_collection_contract_meta(text, None)
        self.assertEqual(contract.get("output_format"), "dashboard")
        self.assertEqual(contract.get("source_kind"), "web")
        self.assertTrue(contract.get("subject"))
        self.assertFalse(contract.get("missing_fields"))
        reply = self.backend.build_collection_clarification_or_contract_reply(text, None)
        self.assertIsNotNone(reply)
        reply_text, meta = reply
        self.assertEqual(meta.get("message_kind"), "collection_contract")
        self.assertEqual(meta.get("downstream"), "chat:data_collection_contract")
        self.assertNotIn("какие поля обязательны", reply_text)

    def test_collection_followup_reuses_previous_research_request_for_short_source_hint(self):
        user_id = self.create_user("market-followup@demo.local")
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Geely market",
            [
                (
                    "user",
                    "Проанализируй рынок автомобилей geely в России в 2024-2025 годах и построй дашборд",
                    {"user_text": "Проанализируй рынок автомобилей geely в России в 2024-2025 годах и построй дашборд"},
                ),
                (
                    "assistant",
                    "Могу собрать данные по этому запросу, но сначала нужно зафиксировать контракт сбора.",
                    {"message_kind": "clarification_request", "downstream": "chat:data_collection_clarification"},
                ),
                (
                    "user",
                    "Собери информацию из интернета",
                    {"user_text": "Собери информацию из интернета"},
                ),
            ],
        )
        with self.backend.db_connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
        effective = self.backend.infer_collection_followup_request_text(rows, message_ids[-1], "Собери информацию из интернета")
        self.assertIn("рынок автомобилей geely", effective.lower())
        self.assertIn("интернета", effective.lower())
        contract = self.backend.build_collection_contract_meta(effective, None)
        self.assertEqual(contract.get("source_kind"), "web")
        self.assertEqual(contract.get("output_format"), "dashboard")
        self.assertFalse(contract.get("missing_fields"))

    def test_post_message_dispatches_chat_task_immediately(self):
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Immediate dispatch', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']
            with patch.object(self.backend, 'dispatch_chat_task_now', return_value=True) as dispatch_mock:
                response = client.post(
                    f'/api/threads/{thread_id}/messages',
                    headers=self.auth_headers(token),
                    json={'content': 'Расскажи про Flatpak'},
                )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        dispatch_mock.assert_called_once_with(payload['chat_task']['id'])

    def test_process_chat_task_collection_route_preempts_dashboard_and_recurring(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Collection priority",
            [
                (
                    "user",
                    "Собери данные с https://example.org в csv по теме LegalAI с полями title, summary и поставь еженедельный мониторинг",
                    {"user_text": "Собери данные с https://example.org в csv по теме LegalAI с полями title, summary и поставь еженедельный мониторинг"},
                ),
                ("assistant", "Готовлю ответ…", {"message_kind": "processing_status", "pending": True}),
            ],
        )
        user_message_id = message_ids[0]
        assistant_message_id = message_ids[1]
        with self.backend.db_connect() as conn:
            baseline_jobs = conn.execute("SELECT COUNT(*) AS cnt FROM jobs WHERE user_id = ?", (user_id,)).fetchone()["cnt"]
            ts = self.backend.now_iso()
            task_id = int(
                conn.execute(
                    """
                    INSERT INTO chat_tasks (
                        thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                    """,
                    (thread_id, user_id, user_message_id, assistant_message_id, "{}", ts),
                ).fetchone()[0]
            )
        with patch.object(self.backend, "execute_web_collection_contract", return_value=(
            "Готово. Собрала данные.",
            {"message_kind": "collection_execution_result", "downstream": "chat:web_collection_result", "attachments": []},
        )) as execute_mock, patch.object(self.backend, "maybe_build_dashboard_reply", wraps=self.backend.maybe_build_dashboard_reply) as dashboard_mock, patch.object(
            self.backend,
            "maybe_create_recurring_job_from_chat",
            wraps=self.backend.maybe_create_recurring_job_from_chat,
        ) as recurring_mock:
            self.assertTrue(self.backend.process_chat_task(task_id))
        self.assertEqual(execute_mock.call_count, 1)
        self.assertEqual(dashboard_mock.call_count, 0)
        self.assertEqual(recurring_mock.call_count, 0)
        with self.backend.db_connect() as conn:
            assistant_message = conn.execute("SELECT meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
            jobs_after = conn.execute("SELECT COUNT(*) AS cnt FROM jobs WHERE user_id = ?", (user_id,)).fetchone()["cnt"]
        self.assertEqual(json.loads(assistant_message["meta_json"])["message_kind"], "collection_execution_result")
        self.assertEqual(jobs_after, baseline_jobs)

    def test_generic_web_collection_contract_does_not_require_explicit_urls(self):
        text = "Собери информацию из источников в интернете в csv по теме LegalAI с полями компания, продукт, ссылка, summary"
        contract = self.backend.build_collection_contract_meta(text, None)
        self.assertEqual(contract.get("source_kind"), "web")
        self.assertEqual(contract.get("output_format"), "csv")
        self.assertEqual(contract.get("subject"), "LegalAI")
        self.assertEqual(contract.get("fields"), ["компания", "продукт", "ссылка", "summary"])
        self.assertNotIn("список URL / сайтов", contract.get("missing_fields") or [])

    def test_combined_collection_request_extracts_analysis_layers(self):
        text = "Собери данные из источников в интернете в csv по теме LegalAI, классифицируй компании по типу и подбери похожие продукты с полями компания, тип, похожий_продукт, summary"
        contract = self.backend.build_collection_contract_meta(text)
        self.assertEqual(contract.get("source_kind"), "web")
        self.assertEqual(contract.get("output_format"), "csv")
        self.assertEqual(contract.get("subject"), "LegalAI")
        self.assertCountEqual(contract.get("analysis_modes") or [], ["classification", "selection", "comparison"])
        self.assertEqual((contract.get("task_layers") or {}).get("root_class"), "data_pipeline")
        self.assertEqual((contract.get("task_layers") or {}).get("stages"), ["acquisition", "analysis", "delivery"])

    def test_attach_assistant_token_accounting_uses_exact_usage_when_available(self):
        meta = self.backend.attach_assistant_token_accounting(
            {"usage": {"prompt_tokens": 111, "completion_tokens": 29, "total_tokens": 140}},
            "Короткий ответ",
        )
        accounting = meta.get("token_accounting") or {}
        self.assertEqual(accounting.get("prompt_tokens"), 111)
        self.assertEqual(accounting.get("completion_tokens"), 29)
        self.assertEqual(accounting.get("total_tokens"), 140)
        self.assertTrue(accounting.get("llm_usage_exact"))
        self.assertGreater(accounting.get("response_text_tokens_estimated") or 0, 0)

    def test_process_chat_task_collection_result_stores_token_accounting(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Token accounting dashboard clarification",
            [
                ("user", "Сделай дашборд по теме LegalAI", {"user_text": "Сделай дашборд по теме LegalAI"}),
                ("assistant", "⏳", {"pending": True, "processing_status": "pending"}),
            ],
        )
        with self.backend.db_connect() as conn:
            ts = self.backend.now_iso()
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, '') RETURNING id
                """,
                (thread_id, user_id, message_ids[0], message_ids[1], "{}", ts),
            )
            task_id = int(cur.fetchone()[0])

        self.assertTrue(self.backend.process_chat_task(task_id))

        with self.backend.db_connect() as conn:
            assistant_message = conn.execute("SELECT meta_json FROM messages WHERE id = ?", (message_ids[1],)).fetchone()
        meta = json.loads(assistant_message["meta_json"] or "{}")
        accounting = meta.get("token_accounting") or {}
        self.assertGreater(accounting.get("response_text_tokens_estimated") or 0, 0)
        self.assertFalse(accounting.get("llm_usage_exact"))
        self.assertEqual(meta.get("message_kind"), "dashboard_result")
        self.assertTrue((meta.get("downstream") or "").startswith("dashboard:"))

    def test_attachment_analysis_file_request_routes_as_collection_pipeline(self):
        text = "Проанализируй эти файлы, классифицируй записи по типам и отдай csv с полями тип, summary"
        attachments = [{"original_name": "input.txt", "relative_path": "uploads/demo/input.txt", "mime_type": "text/plain"}]
        self.assertTrue(self.backend.looks_like_collection_request(text, attachments))
        contract = self.backend.build_collection_contract_meta(text, attachments)
        self.assertEqual(contract.get("source_kind"), "attachment")
        self.assertEqual(contract.get("output_format"), "csv")
        self.assertEqual(contract.get("analysis_modes"), ["classification"])
        self.assertEqual((contract.get("task_layers") or {}).get("stages"), ["acquisition", "analysis", "delivery"])

    def test_enrich_assistant_meta_sets_chat_response_kind_for_generic_llm_reply(self):
        text, meta = self.backend.enrich_assistant_meta(
            {"downstream": "hermes-api-server", "hermes_model": "demo-model"},
            "Готовый аналитический ответ.",
            message_id=123,
        )
        self.assertEqual(text, "Готовый аналитический ответ.")
        self.assertEqual(meta.get("message_kind"), "chat_response")

    def test_uploaded_file_analysis_request_completes_with_collection_artifact(self):
        email = f"upload-smoke-{int(time.time() * 1000)}@demo.local"
        self.create_user(email)
        token = self.login(email)
        thread = self.client.post("/api/threads", headers=self.auth_headers(token), json={"title": "Upload analysis"})
        self.assertEqual(thread.status_code, 201)
        thread_id = thread.get_json()["thread"]["id"]
        with patch.object(
            self.backend,
            "call_hermes_messages",
            return_value=(json.dumps({"rows": [
                {"source_url": "note.txt", "тип": "contract", "summary": "Alpha contract"},
                {"source_url": "note.txt", "тип": "litigation", "summary": "Beta litigation"},
            ]}, ensure_ascii=False), {}),
        ):
            upload_message = self.client.post(
                f"/api/threads/{thread_id}/messages",
                headers=self.auth_headers(token),
                data={
                    "content": "Собери из этих файлов csv, классифицируй записи по типам и отдай файл с полями тип, summary",
                    "files": (io.BytesIO("Alpha contract\nBeta litigation".encode("utf-8")), "note.txt"),
                },
                content_type='multipart/form-data',
            )
            self.assertEqual(upload_message.status_code, 201)
            body = upload_message.get_json()
            self.assertEqual(body["assistant_message"]["meta"]["message_kind"], "processing_status")
            for _ in range(20):
                final_message = self.client.get(f"/api/threads/{thread_id}", headers=self.auth_headers(token)).get_json()["messages"][-1]
                if final_message["meta"].get("message_kind") != "processing_status":
                    break
                time.sleep(0.05)
            else:
                self.fail("uploaded file analysis task did not finish in time")
        self.assertEqual(final_message["meta"]["message_kind"], "collection_execution_result")
        attachments = final_message["meta"].get("attachments") or []
        self.assertEqual(len(attachments), 1)
        csv_text = Path(attachments[0]["local_path"]).read_text(encoding="utf-8")
        self.assertIn("тип,summary,source_url", csv_text)
        self.assertIn("contract", csv_text)

    def test_execute_web_collection_contract_searches_sources_when_urls_not_provided(self):
        text = "Собери информацию из источников в интернете в csv по теме LegalAI с полями компания, продукт, ссылка, summary"
        contract = self.backend.build_collection_contract_meta(text, None)
        documents = [
            {
                "requested_url": "https://legal.example/one",
                "final_url": "https://legal.example/one",
                "title": "Legal One",
                "text": "Legal One overview about LegalAI products.",
            },
            {
                "requested_url": "https://legal.example/two",
                "final_url": "https://legal.example/two",
                "title": "Legal Two",
                "text": "Legal Two overview about LegalAI products.",
            },
        ]
        with patch.object(self.backend, "search_web_source_candidates", return_value=["https://legal.example/one", "https://legal.example/two"]), patch.object(
            self.backend,
            "fetch_web_source_document",
            side_effect=documents,
        ), patch.object(
            self.backend,
            "call_hermes_messages",
            return_value=(json.dumps({"rows": [
                {"source_url": "https://legal.example/one", "компания": "Legal One", "продукт": "Suite", "ссылка": "https://legal.example/one", "summary": "overview"},
                {"source_url": "https://legal.example/two", "компания": "Legal Two", "продукт": "Flow", "ссылка": "https://legal.example/two", "summary": "overview"},
            ]}, ensure_ascii=False), {}),
        ):
            reply_text, meta = self.backend.execute_web_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        manifest = meta.get("task_source_list") or {}
        self.assertEqual(manifest.get("kind"), "web_sources")
        self.assertEqual(len(manifest.get("items") or []), 2)
        self.assertIn("Legal One", Path((meta.get("attachments") or [])[0]["local_path"]).read_text(encoding="utf-8"))
        self.assertIn("Файл:", reply_text)

    def test_search_web_source_candidates_via_hermes_cli_parses_json_urls(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": 'session_id: abc\n["https://legal.example/one", "https://legal.example/two"]', "stderr": ""})()
        with patch.object(self.backend.shutil, "which", return_value="/usr/bin/hermes"), patch.object(self.backend.subprocess, "run", return_value=completed):
            urls = self.backend.search_web_source_candidates_via_hermes_cli("LegalAI", limit=5)
        self.assertEqual(urls, ["https://legal.example/one", "https://legal.example/two"])

    def test_search_web_source_candidates_via_hermes_cli_uses_explicit_home_bin_fallback(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": '["https://legal.example/one"]', "stderr": ""})()
        with patch.object(self.backend.shutil, "which", return_value=None), patch.object(self.backend.os.path, "isfile", return_value=True), patch.object(self.backend.os, "access", return_value=True), patch.object(self.backend.subprocess, "run", return_value=completed) as run_mock:
            urls = self.backend.search_web_source_candidates_via_hermes_cli("LegalAI", limit=5)
        self.assertEqual(urls, ["https://legal.example/one"])
        self.assertIn("/home/hermes/.local/bin/hermes", run_mock.call_args.args[0])

    def test_build_web_search_queries_prefers_broad_subject_first_and_keeps_quoted_fallback(self):
        contract = {"subject": "LegalAI", "fields": ["компания", "продукт", "ссылка"]}
        queries = self.backend.build_web_search_queries(contract)
        self.assertIn("LegalAI", queries)
        self.assertIn("Legal AI market overview", queries)
        self.assertIn('"Legal AI" market overview', queries)
        self.assertLess(queries.index("Legal AI market overview"), queries.index('"Legal AI" market overview'))

    def test_build_web_search_queries_uses_generic_history_family_without_subject_hardcode(self):
        contract = {"subject": "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик", "fields": []}
        queries = self.backend.build_web_search_queries(contract)
        self.assertTrue(any("history" in item for item in queries))
        self.assertTrue(any("evolution" in item for item in queries))
        self.assertFalse(any('OLAP DSS data warehousing' in item for item in queries))

    def test_search_web_source_candidates_falls_back_to_bing_after_duckduckgo_challenge(self):
        ddg_html = '<div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>'
        bing_html = (
            '<li class="b_algo">'
            '<h2><a href="https://www.bing.com/ck/a?!&amp;&amp;u=a1aHR0cHM6Ly9mb3JnZW9mZW1waXJlcy5jb20vc3RhcnQvdmFsaWRhdGU=&amp;ntb=1">Bad</a></h2>'
            '</li>'
            '<li class="b_algo">'
            '<h2><a href="https://www.bing.com/ck/a?!&amp;&amp;u=a1aHR0cHM6Ly9sZWdhbC5leGFtcGxlL29uZQ==&amp;ntb=1">One</a></h2>'
            '</li>'
            '<li class="b_algo">'
            '<h2><a href="https://www.bing.com/ck/a?!&amp;&amp;u=a1aHR0cHM6Ly9sZWdhbC5leGFtcGxlL3R3bw==&amp;ntb=1">Two</a></h2>'
            '</li>'
        )

        class DummyResponse:
            def __init__(self, body: str):
                self._body = body.encode("utf-8")

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(self.backend, "search_web_source_candidates_via_hermes_cli", return_value=[]), patch.object(self.backend.urllib.request, "urlopen", side_effect=[DummyResponse(ddg_html), DummyResponse(bing_html)]):
            urls = self.backend.search_web_source_candidates("LegalAI", limit=5)
        self.assertEqual(urls[:2], ["https://legal.example/one", "https://legal.example/two"])
        self.assertTrue(all("forgeofempires" not in url for url in urls))

    def test_select_relevant_web_documents_prefers_subject_matching_docs(self):
        contract = {"subject": "LegalAI"}
        docs = [
            {"requested_url": "https://example.com/privacy", "final_url": "https://example.com/privacy", "title": "Privacy statement", "text": "general privacy text"},
            {"requested_url": "https://legal.example/overview", "final_url": "https://legal.example/overview", "title": "LegalAI platform overview", "text": "LegalAI platform for legal operations and contract review."},
        ]
        selected = self.backend.select_relevant_web_documents(contract, docs)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["final_url"], "https://legal.example/overview")

    def test_build_collection_relevance_terms_keeps_short_it_acronyms(self):
        terms = self.backend.build_collection_relevance_terms("Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик")
        self.assertIn("bi", terms)
        self.assertIn("business intelligence", terms)
        self.assertNotIn("собери", terms)
        self.assertNotIn("дашборд", terms)

    def test_build_collection_search_profile_extracts_generic_history_intent(self):
        profile = self.backend.build_collection_search_profile({
            "subject": "история развития автомобилей",
            "request_text": "Проанализируй данные в интернете и собери дашборд по истории развития автомобилей",
            "fields": [],
        })
        self.assertEqual(profile.get("intent"), "history")
        self.assertIn("автомобилей", profile.get("subject_terms") or [])

    def test_build_collection_search_profile_extracts_generic_market_intent(self):
        profile = self.backend.build_collection_search_profile({
            "subject": "LegalAI",
            "request_text": "Собери обзор рынка LegalAI и ключевых игроков",
            "fields": ["компания", "продукт", "ссылка"],
        })
        self.assertEqual(profile.get("intent"), "market_overview")
        self.assertIn("LegalAI", profile.get("subject_phrases") or [])

    def test_build_web_search_queries_uses_generic_history_family_without_topic_hardcode(self):
        contract = {
            "subject": "история развития BI-решений и BI-практик",
            "request_text": "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик",
            "fields": [],
        }
        queries = self.backend.build_web_search_queries(contract)
        joined = " || ".join(queries).lower()
        self.assertNotIn("olap", joined)
        self.assertNotIn("dss", joined)
        self.assertNotIn("data warehousing", joined)
        self.assertTrue(any("history" in item.lower() or "timeline" in item.lower() or "evolution" in item.lower() for item in queries))

    def test_build_web_search_queries_history_family_is_topic_agnostic(self):
        contract = {
            "subject": "история развития автомобилей",
            "request_text": "Собери обзор по истории развития автомобилей",
            "fields": [],
        }
        queries = self.backend.build_web_search_queries(contract)
        joined = " || ".join(queries).lower()
        self.assertNotIn("business intelligence", joined)
        self.assertNotIn("olap", joined)
        self.assertTrue(any("history" in item.lower() or "timeline" in item.lower() or "evolution" in item.lower() for item in queries))

    def test_score_web_candidate_set_prefers_diverse_relevant_results(self):
        contract = {
            "subject": "LegalAI",
            "request_text": "Собери обзор рынка LegalAI",
            "fields": ["компания", "продукт", "ссылка"],
        }
        weak_urls = [
            "https://support.example.com/legalai/help",
            "https://support.example.com/legalai/login",
            "https://support.example.com/legalai/privacy",
        ]
        strong_urls = [
            "https://legalai.example/overview",
            "https://market.example/legalai-vendors",
            "https://research.example/legalai-landscape",
        ]
        self.assertGreater(
            self.backend.score_web_candidate_set(contract, strong_urls),
            self.backend.score_web_candidate_set(contract, weak_urls),
        )

    def test_score_web_candidate_set_penalizes_non_topical_noise_sets(self):
        contract = {"subject": "business intelligence", "request_text": "Построй дашборд по истории BI", "fields": []}
        noisy_urls = [
            "https://www.stradivarius.com/fr/",
            "https://www.zalando.fr/stradivarius/",
            "https://www.youtube.com/feed/homepage",
        ]
        topical_urls = [
            "https://en.wikipedia.org/wiki/Business_intelligence",
            "https://www.ibm.com/think/topics/business-intelligence",
            "https://www.cio.com/article/221963/history-of-business-intelligence.html",
        ]
        self.assertGreater(
            self.backend.score_web_candidate_set(contract, topical_urls),
            self.backend.score_web_candidate_set(contract, noisy_urls),
        )

    def test_filter_search_result_urls_ranks_subject_relevant_candidates_higher(self):
        contract = {"subject": "история развития BI-решений и BI-практик"}
        urls = [
            "https://support.google.com/translate/answer/6142474?hl=hu",
            "https://www.ibm.com/think/topics/business-intelligence",
            "https://en.wikipedia.org/wiki/Business_intelligence",
        ]
        filtered = self.backend.filter_search_result_urls(urls, contract=contract, limit=3)
        self.assertEqual(filtered[0], "https://www.ibm.com/think/topics/business-intelligence")
        self.assertIn("https://en.wikipedia.org/wiki/Business_intelligence", filtered)

    def test_filter_search_result_urls_penalizes_generic_training_and_profile_pages(self):
        contract = {"subject": "LegalAI"}
        urls = [
            "https://www.tableau.com/learn/training",
            "https://vendor.example/profiles/legalai-analyst",
            "https://legalai.example/platform-overview",
        ]
        filtered = self.backend.filter_search_result_urls(urls, contract=contract, limit=3)
        self.assertEqual(filtered[0], "https://legalai.example/platform-overview")

    def test_score_web_candidate_set_uses_search_preview_signal_for_generic_urls(self):
        contract = {
            "subject": "LegalAI",
            "request_text": "Собери обзор рынка LegalAI",
            "fields": ["компания", "продукт", "ссылка"],
        }
        weak_candidates = [
            {
                "url": "https://example.com/page-a",
                "title": "Overview",
                "snippet": "General business software landing page",
            },
            {
                "url": "https://example.com/page-b",
                "title": "Product page",
                "snippet": "General enterprise workflow tool",
            },
        ]
        strong_candidates = [
            {
                "url": "https://example.com/page-a",
                "title": "LegalAI market overview",
                "snippet": "LegalAI vendors, product categories, and market landscape.",
            },
            {
                "url": "https://example.com/page-b",
                "title": "LegalAI platform comparison",
                "snippet": "Comparison of LegalAI products and contract review tools.",
            },
        ]
        self.assertGreater(
            self.backend.score_web_candidate_set(contract, strong_candidates),
            self.backend.score_web_candidate_set(contract, weak_candidates),
        )

    def test_select_relevant_web_documents_penalizes_generic_redirect_and_training_pages(self):
        contract = {"subject": "business intelligence"}
        docs = [
            {
                "requested_url": "https://www.tableau.com/learn/training/20231",
                "final_url": "https://www.tableau.com/learn/training",
                "title": "Free Training Videos - Tableau",
                "text": "Training catalog and onboarding videos for Tableau users." * 4,
            },
            {
                "requested_url": "https://www.ibm.com/topics/business-intelligence",
                "final_url": "https://www.ibm.com/think/topics/business-intelligence",
                "title": "What Is Business Intelligence (BI)? | IBM",
                "text": "Business intelligence combines data warehousing, reporting, OLAP, dashboards, and decision support capabilities across enterprise teams." * 4,
            },
        ]
        selected = self.backend.select_relevant_web_documents(contract, docs)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["final_url"], "https://www.ibm.com/think/topics/business-intelligence")

    def test_select_relevant_web_documents_rejects_irrelevant_help_pages_for_bi_query(self):
        contract = {"subject": "история развития BI-решений и BI-практик"}
        docs = [
            {
                "requested_url": "https://support.google.com/translate/answer/6142474?hl=hu",
                "final_url": "https://support.google.com/translate/answer/6142474?hl=hu",
                "title": "Valós idejű beszélgetésfordítás hallgatása",
                "text": "Google Translate help page about live speech translation. " * 20,
            },
            {
                "requested_url": "https://www.ibm.com/think/topics/business-intelligence",
                "final_url": "https://www.ibm.com/think/topics/business-intelligence",
                "title": "What is business intelligence?",
                "text": "Business intelligence evolved from decision support systems, data warehousing, and OLAP before self-service analytics.",
            },
        ]
        selected = self.backend.select_relevant_web_documents(contract, docs)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["final_url"], "https://www.ibm.com/think/topics/business-intelligence")

    def test_execute_web_collection_contract_rejects_irrelevant_documents(self):
        text = "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик"
        contract = self.backend.build_collection_contract_meta(text, None)
        bad_doc = {
            "requested_url": "https://support.google.com/translate/answer/6142474?hl=hu",
            "final_url": "https://support.google.com/translate/answer/6142474?hl=hu",
            "title": "Valós idejű beszélgetésfordítás hallgatása",
            "text": "Google Translate help page about live speech translation. " * 20,
        }
        with patch.object(self.backend, "search_web_source_candidates", return_value=[bad_doc["requested_url"]]), patch.object(
            self.backend,
            "fetch_web_source_document",
            return_value=bad_doc,
        ):
            with self.assertRaises(self.backend.ApiError) as exc:
                self.backend.execute_web_collection_contract(contract)
        self.assertIn("web_collection_documents_irrelevant", str(exc.exception))

    def test_execute_web_collection_contract_returns_partial_attachment_when_sources_found_but_documents_unavailable(self):
        contract = {
            'source_kind': 'web',
            'source_label': 'Интернет-источники',
            'source_items': [],
            'subject': 'LegalAI',
            'output_format': 'xlsx',
            'fields': ['title', 'url'],
            'analysis_modes': [],
            'request_text': 'Собери по LegalAI ссылки и источники в xlsx',
        }
        manifest = {
            'query': 'legalai market overview',
            'items': [
                {'requested_url': 'https://example.com/a', 'title': 'A', 'domain': 'example.com', 'source_rank': 1, 'availability_level': 'snippet_only', 'snippet': 'LegalAI market overview and vendors'},
                {'requested_url': 'https://example.com/b', 'title': 'B', 'domain': 'example.com', 'source_rank': 2, 'availability_level': 'discovered_only'},
            ]
        }
        with patch.object(self.backend, 'resolve_web_collection_sources', return_value=(['https://example.com/a', 'https://example.com/b'], manifest)), \
             patch.object(self.backend, 'fetch_web_source_document', side_effect=self.backend.ApiError('upstream_timeout', 502)):
            reply_text, meta = self.backend.execute_web_collection_contract(contract)

        self.assertEqual(meta['message_kind'], 'collection_execution_result')
        self.assertTrue(meta.get('partial_result'))
        self.assertEqual(meta.get('status_note'), 'sources_found_but_documents_unavailable')
        self.assertEqual(meta.get('fallback_result_kind'), 'source_shortlist')
        self.assertEqual(len(meta.get('attachments') or []), 1)
        self.assertEqual(len(meta.get('web_sources') or []), 2)
        self.assertEqual(len(meta.get('web_sources_skipped') or []), 2)
        self.assertEqual(meta['web_sources'][0].get('domain'), 'example.com')
        self.assertEqual(meta['web_sources'][0].get('query'), 'legalai market overview')
        self.assertEqual(meta['web_sources'][0].get('availability_level'), 'snippet_only')
        self.assertEqual(meta['web_sources'][0].get('snippet'), 'LegalAI market overview and vendors')
        self.assertIn('полезный shortlist источников', reply_text)
        self.assertIn('краткие описания', reply_text)

    def test_execute_web_collection_contract_builds_hybrid_artifact_when_some_sources_fail(self):
        contract = {
            'source_kind': 'web',
            'source_label': 'Интернет-источники',
            'source_items': [],
            'subject': 'LegalAI',
            'output_format': 'csv',
            'fields': ['summary'],
            'analysis_modes': [],
            'request_text': 'Собери по LegalAI данные и сохрани в csv',
        }
        manifest = {
            'query': 'legalai market overview',
            'items': [
                {'requested_url': 'https://example.com/a', 'title': 'A', 'domain': 'example.com', 'source_rank': 1, 'availability_level': 'snippet_only', 'snippet': 'Vendor landscape'},
                {'requested_url': 'https://example.com/b', 'title': 'B', 'domain': 'example.com', 'source_rank': 2, 'availability_level': 'snippet_only', 'snippet': 'Funding and market traction'},
            ]
        }

        def fake_fetch(url):
            if url.endswith('/a'):
                return {
                    'requested_url': url,
                    'final_url': url,
                    'title': 'A',
                    'content_type': 'text/html',
                    'text': 'LegalAI vendors and market overview',
                    'meta_description': 'Vendor landscape',
                }
            raise self.backend.ApiError('upstream_timeout', 502)

        with patch.object(self.backend, 'resolve_web_collection_sources', return_value=(['https://example.com/a', 'https://example.com/b'], manifest)), \
             patch.object(self.backend, 'fetch_web_source_document', side_effect=fake_fetch), \
             patch.object(self.backend, 'select_relevant_web_documents', side_effect=lambda contract, docs: docs), \
             patch.object(self.backend, 'structure_web_collection_rows', return_value=[{'summary': 'Краткая сводка', 'source_url': 'https://example.com/a'}]):
            reply_text, meta = self.backend.execute_web_collection_contract(contract)

        self.assertEqual(meta['message_kind'], 'collection_execution_result')
        self.assertTrue(meta.get('partial_result'))
        self.assertEqual(meta.get('status_note'), 'sources_partially_unavailable')
        self.assertEqual(meta.get('fallback_result_kind'), 'hybrid_content_plus_shortlist')
        self.assertEqual(len(meta.get('web_sources_skipped') or []), 1)
        self.assertEqual(len(meta.get('web_source_shortlist') or []), 2)
        self.assertIn('shortlist по недоступным источникам', reply_text)
        self.assertEqual(meta['collection_rows_preview'][0].get('record_type'), 'document_row')
        self.assertTrue(any(row.get('record_type') == 'source_shortlist' for row in (meta.get('web_source_shortlist') or [])))
        attachment = (meta.get('attachments') or [None])[0]
        self.assertIsNotNone(attachment)
        with open(attachment['local_path'], 'r', encoding='utf-8') as handle:
            csv_text = handle.read()
        self.assertIn('record_type', csv_text)
        self.assertIn('document_row', csv_text)
        self.assertIn('source_shortlist', csv_text)
        self.assertIn('Funding and market traction', csv_text)

    def test_build_web_source_manifest_items_enriches_urls_with_domain_query_and_rank(self):
        rows = self.backend.build_web_source_manifest_items(
            [
                {'url': 'https://example.com/a?x=1', 'snippet': 'Alpha result'},
                {'url': 'https://sub.example.org/path'},
            ],
            query='legalai vendors',
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['domain'], 'example.com')
        self.assertEqual(rows[0]['query'], 'legalai vendors')
        self.assertEqual(rows[0]['source_rank'], 1)
        self.assertEqual(rows[0]['availability_level'], 'snippet_only')
        self.assertEqual(rows[0]['snippet'], 'Alpha result')
        self.assertEqual(rows[1]['domain'], 'sub.example.org')

    def test_extract_search_result_previews_parses_title_snippet_and_url(self):
        body = '''
        <html><body>
          <div class="result">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Flegalai">LegalAI vendors</a>
            <a class="result__snippet">Market overview and key players in LegalAI.</a>
          </div>
        </body></html>
        '''
        previews = self.backend.extract_search_result_previews(body, limit=5)
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]['url'], 'https://example.com/legalai')
        self.assertEqual(previews[0]['title'], 'LegalAI vendors')
        self.assertIn('Market overview', previews[0]['snippet'])
        self.assertEqual(previews[0]['domain'], 'example.com')

    def test_resolve_web_collection_sources_prefers_more_relevant_later_query(self):
        contract = {"subject": "Проанализируй данные в интернете и собери дашборд по истории развития BI-решений и BI-практик", "fields": []}
        queries = ["bad query", "good query"]
        by_query = {
            "bad query": ["https://support.google.com/translate/answer/6142474?hl=hu"],
            "good query": ["https://en.wikipedia.org/wiki/Business_intelligence"],
        }
        with patch.object(self.backend, "build_web_search_queries", return_value=queries), patch.object(
            self.backend,
            "search_web_source_candidates",
            side_effect=lambda query, limit=5, contract=None: by_query[query],
        ):
            candidates, _manifest = self.backend.resolve_web_collection_sources(contract)
        self.assertEqual(candidates, by_query["good query"])

    def test_execute_web_collection_contract_uses_expanded_source_limit(self):
        text = "Собери данные из интернета по рынку LegalAI и дай csv с полями компания, продукт, ссылка"
        contract = self.backend.build_collection_contract_meta(text, None)
        source_urls = [f"https://legal.example/{idx}" for idx in range(1, 9)]
        documents = [
            {
                "requested_url": url,
                "final_url": url,
                "title": f"Legal {idx}",
                "text": f"LegalAI market overview for company {idx}.",
            }
            for idx, url in enumerate(source_urls, start=1)
        ]
        rows = [
            {
                "source_url": url,
                "компания": f"Legal {idx}",
                "продукт": f"Suite {idx}",
                "ссылка": url,
            }
            for idx, url in enumerate(source_urls, start=1)
        ]
        with patch.object(self.backend, "resolve_web_collection_sources", return_value=(source_urls, {"kind": "web_sources", "sources": []})), patch.object(
            self.backend,
            "fetch_web_source_document",
            side_effect=documents,
        ) as fetch_mock, patch.object(
            self.backend,
            "call_hermes_messages",
            return_value=(json.dumps({"rows": rows}, ensure_ascii=False), {}),
        ):
            _reply_text, meta = self.backend.execute_web_collection_contract(contract)
        self.assertEqual(fetch_mock.call_count, 8)
        self.assertEqual(len(meta.get("web_sources") or []), 8)

    def test_execute_web_collection_contract_skips_forbidden_source_if_others_succeed(self):
        text = "Собери информацию из источников в интернете в csv по теме LegalAI с полями компания, продукт, ссылка, summary"
        contract = self.backend.build_collection_contract_meta(text, None)
        good_doc = {
            "requested_url": "https://legal.example/good",
            "final_url": "https://legal.example/good",
            "title": "Legal Good",
            "text": "Legal Good overview about LegalAI products.",
        }
        with patch.object(self.backend, "search_web_source_candidates", return_value=["https://bad.example/blocked", "https://legal.example/good"]), patch.object(
            self.backend,
            "fetch_web_source_document",
            side_effect=[urllib.error.HTTPError("https://bad.example/blocked", 403, "Forbidden", hdrs=None, fp=io.BytesIO(b"")), good_doc],
        ), patch.object(
            self.backend,
            "call_hermes_messages",
            return_value=(json.dumps({"rows": [
                {"source_url": "https://legal.example/good", "компания": "Legal Good", "продукт": "Suite", "ссылка": "https://legal.example/good", "summary": "overview"},
            ]}, ensure_ascii=False), {}),
        ):
            reply_text, meta = self.backend.execute_web_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        self.assertEqual(len(meta.get("web_sources") or []), 1)
        self.assertEqual(len(meta.get("web_sources_skipped") or []), 1)
        self.assertIn("Пропущено источников: 1", reply_text)

    def test_execute_attachment_collection_contract_creates_real_csv_artifact(self):
        text = "Собери из этих файлов в csv по теме проект КП с полями workstream, estimate_hours, source_note"
        attachments = [
            {
                "original_name": "tz.txt",
                "relative_path": "uploads/demo/tz.txt",
                "mime_type": "text/plain",
                "text_extracted": True,
                "preview_text": "ТЗ по внедрению CRM",
                "extracted_text": "Нужно внедрение CRM, интеграция с 1С, обучение пользователей.",
            },
            {
                "original_name": "prior-kp.txt",
                "relative_path": "uploads/demo/prior-kp.txt",
                "mime_type": "text/plain",
                "text_extracted": True,
                "preview_text": "Прошлое КП",
                "extracted_text": "В похожем проекте были workstreams: discovery, integration, training.",
            },
        ]
        contract = self.backend.build_collection_contract_meta(text, attachments)
        with patch.object(
            self.backend,
            "call_hermes_messages",
            return_value=(json.dumps({"rows": [
                {"source_url": "tz.txt", "workstream": "integration", "estimate_hours": "120", "source_note": "1С integration"},
                {"source_url": "prior-kp.txt", "workstream": "training", "estimate_hours": "24", "source_note": "analogue"},
            ]}, ensure_ascii=False), {}),
        ):
            reply_text, meta = self.backend.execute_attachment_collection_contract(contract, attachments)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        self.assertEqual(meta.get("downstream"), "chat:attachment_collection_result")
        bundle = meta.get("task_source_list") or {}
        self.assertEqual(bundle.get("kind"), "attachment_bundle")
        csv_text = Path((meta.get("attachments") or [])[0]["local_path"]).read_text(encoding="utf-8")
        self.assertIn("workstream,estimate_hours,source_note,source_url", csv_text)
        self.assertIn("integration", csv_text)
        self.assertIn("Файлов в bundle: 2", reply_text)

    def test_execute_api_collection_contract_creates_real_csv_artifact(self):
        text = "Собери через API https://api.example.test/items в csv по теме catalog с полями id, name, status"
        contract = self.backend.build_collection_contract_meta(text, None)
        payload = [{"id": 1, "name": "Alpha", "status": "active"}, {"id": 2, "name": "Beta", "status": "draft"}]
        with patch.object(self.backend, "fetch_api_source_payload", return_value=("https://api.example.test/items", payload)):
            reply_text, meta = self.backend.execute_api_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        self.assertEqual(meta.get("downstream"), "chat:api_collection_result")
        task_config = meta.get("task_source_list") or {}
        self.assertEqual(task_config.get("kind"), "api_task")
        csv_text = Path((meta.get("attachments") or [])[0]["local_path"]).read_text(encoding="utf-8")
        self.assertIn("id,name,status,source_url", csv_text)
        self.assertIn("Alpha", csv_text)
        self.assertIn("API-источников обработано: 1", reply_text)

    def test_proposal_intent_is_not_triggered_for_regular_collection_request(self):
        text = "Собери данные с https://example.org в csv по теме LegalAI с полями title, summary"
        contract = self.backend.build_collection_contract_meta(text, None)
        self.assertEqual(contract.get("composition_mode"), "")
        self.assertEqual(contract.get("output_format"), "csv")

    def test_proposal_contract_extracts_budget_timeline_and_team_hints(self):
        text = "Подготовь проект КП по внедрению CRM: бюджет до 3 млн руб, срок 8 недель, команда solution architect и backend developer"
        contract = self.backend.build_collection_contract_meta(text, None)
        self.assertEqual(contract.get("composition_mode"), "proposal_bundle")
        self.assertIn("3 млн", contract.get("budget_hint") or "")
        self.assertIn("8 недель", contract.get("timeline_hint") or "")
        self.assertTrue(any("solution architect" in item.lower() or "backend developer" in item.lower() for item in (contract.get("team_constraints") or [])))

    def test_execute_attachment_collection_contract_creates_proposal_artifact_only_on_explicit_intent(self):
        text = "Собери из этих файлов и подготовь проект КП с оценкой стоимости и ресурсов по теме CRM внедрение"
        attachments = [
            {
                "original_name": "tz.txt",
                "relative_path": "uploads/demo/tz.txt",
                "mime_type": "text/plain",
                "text_extracted": True,
                "preview_text": "ТЗ по внедрению CRM",
                "extracted_text": "Нужно внедрение CRM, интеграция с 1С, обучение пользователей.",
            },
            {
                "original_name": "prior-kp.txt",
                "relative_path": "uploads/demo/prior-kp.txt",
                "mime_type": "text/plain",
                "text_extracted": True,
                "preview_text": "Прошлое КП",
                "extracted_text": "В похожем проекте были workstreams: discovery, integration, training.",
            },
        ]
        contract = self.backend.build_collection_contract_meta(text, attachments)
        self.assertEqual(contract.get("composition_mode"), "proposal_bundle")
        self.assertEqual(contract.get("output_format"), "md")
        with patch.object(
            self.backend,
            "call_hermes_messages",
            side_effect=[
                (json.dumps({"rows": [{"source_url": "tz.txt"}, {"source_url": "prior-kp.txt"}]}, ensure_ascii=False), {}),
                (json.dumps({
                    "title": "Проект КП по CRM",
                    "executive_summary": "Подготовлен черновик КП на основе ТЗ и аналогов.",
                    "confirmed_facts": ["Есть запрос на внедрение CRM и интеграцию с 1С"],
                    "analogs": ["В прошлой подаче были discovery, integration, training"],
                    "hypotheses": ["Оценка часов требует уточнения по числу пользователей"],
                    "workstreams": [{"name": "Integration", "scope": "1С integration", "estimate_hours": "120", "team_role": "Solution Architect", "notes": "Предварительная оценка"}],
                    "cost_notes": ["Стоимость зависит от глубины интеграции"],
                    "resource_plan": ["Architect", "Backend Engineer"],
                    "risks": ["Неполное ТЗ"],
                    "open_questions": ["Сколько пользователей в первом контуре?"]
                }, ensure_ascii=False), {}),
            ],
        ):
            reply_text, meta = self.backend.execute_attachment_collection_contract(contract, attachments)
        self.assertEqual(meta.get("message_kind"), "collection_composition_result")
        self.assertEqual(meta.get("downstream"), "chat:attachment_collection_result:proposal")
        prepared_attachments = meta.get("attachments") or []
        self.assertGreaterEqual(len(prepared_attachments), 1)
        proposal_attachment = prepared_attachments[0]
        self.assertTrue(Path(proposal_attachment.get("local_path")).exists())
        proposal_text = Path(proposal_attachment.get("local_path")).read_text(encoding="utf-8")
        self.assertIn("# Проект КП по CRM", proposal_text)
        self.assertIn("Подтверждённые факты", proposal_text)
        self.assertIn("Режим: proposal_bundle", reply_text)

    def test_serialize_message_injects_attachment_download_url(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Attachment test",
            [
                ("assistant", "Готово", {"attachments": [{"original_name": "demo.csv", "local_path": __file__, "mime_type": "text/csv"}]})
            ],
        )
        with self.backend.db_connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_ids[0],)).fetchone()
        payload = self.backend.serialize_message(row)
        attachments = payload.get("meta", {}).get("attachments") or []
        self.assertEqual(len(attachments), 1)
        self.assertIn(f"/api/messages/{message_ids[0]}/attachments/0", attachments[0].get("download_url", ""))

    def test_job_run_surface_serialization_exposes_public_status_and_result_kind(self):
        run = self.backend.serialize_job_run_row({
            "status": "success",
            "summary": "Готов отчёт с файлом",
            "result_text": "Готово\n\nMEDIA:/tmp/demo.txt",
            "error_text": "",
            "delivered_to_json": json.dumps([{"user_id": 1}], ensure_ascii=False),
            "finished_at": "2026-06-24T10:15:00+00:00",
            "duration_ms": 2400,
        })
        self.assertEqual(run["public_status"], "completed")
        self.assertEqual(run["result_kind"], "file")
        self.assertEqual(run["delivered_count"], 1)
        self.assertEqual(run["status_reason"], "delivered")
        self.assertEqual(run["status_detail"], "Готов отчёт с файлом")
        self.assertEqual(run["delivery_summary"], "Доставлено: 1")
        self.assertEqual(run["finished_at"], "2026-06-24T10:15:00+00:00")
        self.assertEqual(run["duration_ms"], 2400)

        degraded_run = self.backend.serialize_job_run_row({
            "status": "success",
            "summary": "Отчёт готов с ограничениями",
            "result_text": "Сводка собрана частично. Некоторые источники недоступны.",
            "error_text": "",
            "delivered_to_json": "[]",
        })
        self.assertEqual(degraded_run["public_status"], "completed_with_limitations")
        self.assertEqual(degraded_run["result_kind"], "text")
        self.assertEqual(degraded_run["status_reason"], "not_delivered")
        self.assertEqual(degraded_run["delivery_summary"], "Не доставлено")

        empty_run = self.backend.serialize_job_run_row({
            "status": "success",
            "summary": "Новых сигналов не найдено",
            "result_text": "",
            "error_text": "",
            "delivered_to_json": "[]",
        })
        self.assertEqual(empty_run["public_status"], "empty_result")
        self.assertEqual(empty_run["result_kind"], "empty")
        self.assertEqual(empty_run["status_reason"], "no_signal")
        self.assertEqual(empty_run["status_detail"], "Новых сигналов не найдено")

        failed_run = self.backend.serialize_job_run_row({
            "status": "error",
            "summary": "",
            "result_text": "",
            "error_text": "HTTP 500 upstream",
            "delivered_to_json": "[]",
        })
        self.assertEqual(failed_run["public_status"], "failed")
        self.assertEqual(failed_run["result_kind"], "error")
        self.assertEqual(failed_run["status_reason"], "error")
        self.assertEqual(failed_run["status_detail"], "HTTP 500 upstream")

    def test_row_to_job_dict_exposes_last_run_contract(self):
        auth = self.backend.AuthUser(id=1, email="admin@demo.local", role="admin")
        with self.backend.db_connect() as conn:
            row = conn.execute("SELECT * FROM jobs ORDER BY id ASC LIMIT 1").fetchone()
            conn.execute(
                "UPDATE jobs SET last_run_at = ?, last_run_status = ?, last_run_summary = ?, last_error = ? WHERE id = ?",
                (
                    "2026-06-24T10:20:00+00:00",
                    "success",
                    "Отчёт доставлен в Telegram Home",
                    "",
                    row["id"],
                ),
            )
            updated = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
            payload = self.backend.row_to_job_dict(conn, updated, auth=auth, include_details=False)

        self.assertEqual(payload["last_run_public_status"], "completed")
        self.assertEqual(payload["last_run_summary"], "Отчёт доставлен в Telegram Home")
        self.assertEqual(payload["last_run_status_reason"], "delivered")
        self.assertEqual(payload["last_run_status_detail"], "Отчёт доставлен в Telegram Home")
        self.assertEqual(payload["last_run_delivery_summary"], "Есть результат последнего запуска")

    def test_serialize_message_adds_surface_metadata(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Surface test",
            [
                ("assistant", "Нужно уточнить формат результата", {"message_kind": "clarification_request"}),
                ("assistant", "Готов дашборд", {"dashboard_artifact": {"path": "/tmp/dashboard.md"}}),
            ],
        )
        with self.backend.db_connect() as conn:
            clarification = conn.execute("SELECT * FROM messages WHERE id = ?", (message_ids[0],)).fetchone()
            artifact = conn.execute("SELECT * FROM messages WHERE id = ?", (message_ids[1],)).fetchone()
        clarification_payload = self.backend.serialize_message(clarification)
        artifact_payload = self.backend.serialize_message(artifact)
        self.assertEqual(clarification_payload.get("surface", {}).get("status"), "needs_clarification")
        self.assertEqual(clarification_payload.get("surface", {}).get("entity_kind"), "clarification")
        self.assertEqual(artifact_payload.get("surface", {}).get("entity_kind"), "artifact")
        self.assertEqual(artifact_payload.get("surface", {}).get("status"), "completed")

    def test_serialize_message_adds_recurring_summary_envelope_for_job_delivery(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Recurring delivery surface",
            [
                (
                    "assistant",
                    "Ежедневный дайджест собран и отправлен в Telegram Home.",
                    {
                        "source": "job_run",
                        "message_kind": "job_delivery",
                        "summary": "Ежедневный дайджест собран и отправлен в Telegram Home.",
                        "delivered_to_json": json.dumps([{"chat_id": "telegram:home"}], ensure_ascii=False),
                    },
                )
            ],
        )
        with self.backend.db_connect() as conn:
            delivery = conn.execute("SELECT * FROM messages WHERE id = ?", (message_ids[0],)).fetchone()
        payload = self.backend.serialize_message(delivery)
        recurring = payload.get("meta", {}).get("recurring_summary") or {}
        self.assertEqual(payload.get("surface", {}).get("entity_kind"), "job_delivery")
        self.assertEqual(payload.get("surface", {}).get("status"), "completed")
        self.assertTrue(payload.get("surface", {}).get("has_recurring_summary"))
        self.assertEqual(recurring.get("status"), "completed")
        self.assertEqual(recurring.get("status_reason"), "result_ready")
        self.assertEqual(recurring.get("delivery_summary"), "Доставка не зафиксирована")
        self.assertTrue(recurring.get("has_result"))
        self.assertEqual(recurring.get("delivered_count"), 1)

    def test_serialize_message_adds_recurring_summary_envelope_for_processing_status(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        _, message_ids = self.create_thread_with_messages(
            user_id,
            "Recurring status surface",
            [
                (
                    "assistant",
                    "Сбор мониторинга продолжается",
                    {
                        "message_kind": "processing_status",
                        "pending": True,
                        "recurring_summary": {
                            "status": "running",
                            "summary": "Сбор мониторинга продолжается",
                            "status_reason": "in_progress",
                            "delivery_summary": "Выполнение продолжается",
                            "result_kind": "in_progress",
                            "has_result": False,
                            "has_limitations": False,
                        },
                    },
                )
            ],
        )
        with self.backend.db_connect() as conn:
            pending = conn.execute("SELECT * FROM messages WHERE id = ?", (message_ids[0],)).fetchone()
        payload = self.backend.serialize_message(pending)
        recurring = payload.get("meta", {}).get("recurring_summary") or {}
        self.assertEqual(payload.get("surface", {}).get("entity_kind"), "processing_status")
        self.assertEqual(payload.get("surface", {}).get("status"), "running")
        self.assertTrue(payload.get("surface", {}).get("has_recurring_summary"))
        self.assertEqual(recurring.get("status"), "running")
        self.assertEqual(recurring.get("status_reason"), "in_progress")
        self.assertEqual(recurring.get("result_kind"), "in_progress")
        self.assertFalse(recurring.get("has_result"))

    def test_serialize_job_run_marks_stuck_running_as_failed(self):
        stale_started_at = self.backend.now_iso(self.backend.now_utc() - self.backend.timedelta(seconds=self.backend.JOB_RUN_STUCK_SECONDS + 5))
        run = self.backend.serialize_job_run_row({
            "status": "running",
            "started_at": stale_started_at,
            "finished_at": None,
            "summary": "",
            "result_text": "",
            "error_text": "",
            "delivered_to_json": "[]",
        })
        self.assertEqual(run["public_status"], "failed")
        self.assertEqual(run["status_reason"], "stuck")
        self.assertTrue(run["is_stuck"])
        self.assertIn("повторного выполнения", run["status_detail"])

    def test_serialize_message_marks_stuck_processing_status(self):
        stale_created_at = self.backend.now_iso(self.backend.now_utc() - self.backend.timedelta(seconds=self.backend.CHAT_TASK_STUCK_SECONDS + 5))
        payload = self.backend.serialize_message({
            "id": 999001,
            "role": "assistant",
            "content": "Готовлю ответ…",
            "created_at": stale_created_at,
            "meta_json": json.dumps({
                "message_kind": "processing_status",
                "pending": True,
            }, ensure_ascii=False),
        })
        recurring = payload.get("meta", {}).get("recurring_summary") or {}
        self.assertEqual(payload.get("surface", {}).get("status"), "failed")
        self.assertTrue(payload.get("surface", {}).get("has_recurring_summary"))
        self.assertEqual(recurring.get("status"), "failed")
        self.assertEqual(recurring.get("status_reason"), "stuck")
        self.assertTrue(recurring.get("is_stuck"))

    def test_recover_stuck_chat_tasks_resets_running_task_to_pending(self):
        with self.backend.db_connect() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", ("misha@demo.local",)).fetchone()
        user_id = int(user_row["id"])
        thread_id, message_ids = self.create_thread_with_messages(
            user_id,
            "Stuck recovery",
            [
                ("user", "Проверь зависшую задачу", {"user_text": "Проверь зависшую задачу"}),
                ("assistant", "Готовлю ответ…", {"message_kind": "processing_status", "pending": True}),
            ],
        )
        user_message_id = message_ids[0]
        assistant_message_id = message_ids[1]
        stale_started_at = self.backend.now_iso(self.backend.now_utc() - self.backend.timedelta(seconds=self.backend.CHAT_TASK_STUCK_SECONDS + 5))
        created_at = self.backend.now_iso(self.backend.now_utc() - self.backend.timedelta(seconds=self.backend.CHAT_TASK_STUCK_SECONDS + 10))
        with self.backend.db_connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO chat_tasks (
                    thread_id, user_id, user_message_id, assistant_message_id, status, request_policy_json, created_at, started_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, NULL, '') RETURNING id
                """,
                (thread_id, user_id, user_message_id, assistant_message_id, json.dumps({}, ensure_ascii=False), created_at, stale_started_at),
            )
            task_id = int(cur.fetchone()[0])
        recovered = self.backend.recover_stuck_chat_tasks()
        self.assertEqual(recovered, 1)
        with self.backend.db_connect() as conn:
            task = conn.execute("SELECT status, started_at, last_error FROM chat_tasks WHERE id = ?", (task_id,)).fetchone()
            assistant = conn.execute("SELECT content, meta_json FROM messages WHERE id = ?", (assistant_message_id,)).fetchone()
        meta = json.loads(assistant["meta_json"] or "{}")
        self.assertEqual(task["status"], "pending")
        self.assertIsNone(task["started_at"])
        self.assertEqual(assistant["content"], "Готовлю ответ…")
        self.assertTrue(meta.get("pending"))
        self.assertTrue(meta.get("recovered_after_stuck"))
        self.assertIn("тайм-аута", meta.get("status_label", ""))


if __name__ == "__main__":
    unittest.main()
