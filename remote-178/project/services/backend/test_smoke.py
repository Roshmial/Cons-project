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
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import timedelta
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
        module_path = Path(__file__).resolve().parent / "app.py"
        if str(module_path.parent) not in sys.path:
            sys.path.insert(0, str(module_path.parent))
        spec = importlib.util.spec_from_file_location("hermes_web_backend_test_app", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
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

        pdf_response = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=pdf",
            headers=self.auth_headers(token),
        )
        self.assertEqual(pdf_response.status_code, 200)
        self.assertIn("application/pdf", pdf_response.headers.get("Content-Type", ""))
        self.assertTrue(pdf_response.get_data().startswith(b"%PDF"))

        unsupported = self.client.get(
            f"/api/messages/{assistant_message_id}/export?format=epub",
            headers=self.auth_headers(token),
        )
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(unsupported.get_json()["error"], "unsupported_export_format")

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
                ("user", "Важно: лучше сначала давать короткий вывод.", {}),
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

    def test_detect_message_export_format_does_not_trigger_on_docx_filename_only(self):
        self.assertIsNone(self.backend.detect_message_export_format('Проанализируй файл ТЗ2.docx'))
        self.assertIsNone(self.backend.detect_message_export_format('Разбери приложенный документ docx и дай выводы в чат'))
        self.assertEqual(self.backend.detect_message_export_format('Отправь мне файл в docx'), 'docx')
        self.assertEqual(self.backend.detect_message_export_format('А где файл?'), 'docx')

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
        with self.backend.app.test_client() as client:
            with self.backend.db_connect() as conn:
                token = self.backend.issue_session(conn, 1)
            thread_response = client.post(
                '/api/threads',
                headers=self.auth_headers(token),
                json={'title': 'Presentation thread', 'preview': 'Preview'},
            )
            self.assertEqual(thread_response.status_code, 201)
            thread_id = thread_response.get_json()['thread']['id']

            seed_response = client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Дай короткий черновик по Flatpak'},
            )
            self.assertEqual(seed_response.status_code, 201)
            seed_body = seed_response.get_json()
            seed_task_id = seed_body['chat_task']['id']
            seed_assistant_id = seed_body['assistant_message']['id']

            original_process = self.backend.process_chat_task
            original_call = self.backend.call_hermes_api
            original_generated_call = self.backend.call_generated_file_content
            try:
                self.backend.call_hermes_api = lambda *args, **kwargs: ('Вот короткий старый черновик', {'source': 'test'})
                self.assertTrue(original_process(seed_task_id))
            finally:
                self.backend.call_hermes_api = original_call

            request_response = client.post(
                f'/api/threads/{thread_id}/messages',
                headers=self.auth_headers(token),
                json={'content': 'Пришли мне полноценный концепт презентации по Flatpak в виде файла'},
            )
            self.assertEqual(request_response.status_code, 201)
            request_body = request_response.get_json()
            task_id = request_body['chat_task']['id']
            assistant_id = request_body['assistant_message']['id']

            try:
                self.backend.call_generated_file_content = lambda *args, **kwargs: ('Новый полноценный концепт презентации по Flatpak', {'source': 'test'})
                self.assertTrue(original_process(task_id))
            finally:
                self.backend.call_generated_file_content = original_generated_call

        with self.backend.db_connect() as conn:
            row = conn.execute('SELECT content, meta_json FROM messages WHERE id = ?', (assistant_id,)).fetchone()
        meta = json.loads(row['meta_json'])
        self.assertEqual(meta['message_kind'], 'file_response')
        self.assertEqual(meta['export_format'], 'docx')
        self.assertEqual(meta['source'], 'generated_file_response')
        self.assertTrue(meta['generated_from_request'])
        self.assertNotIn('exported_message_id', meta)
        self.assertIn('Собрала новый ответ в файл', row['content'])
        attachment = meta['attachments'][0]
        self.assertTrue(os.path.exists(attachment['local_path']))
        self.assertIn('Новый полноценный концепт презентации по Flatpak', attachment['preview_excerpt'])
        self.assertNotIn('Вот короткий старый черновик', attachment['preview_excerpt'])
        self.assertNotEqual(seed_assistant_id, assistant_id)

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
                json={'content': 'Пришли мне полноценный концепт презентации по Flatpak в виде файла'},
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
                "text": "Example Org text about test dataset and overview.",
            },
            {
                "requested_url": "https://example.com",
                "final_url": "https://example.com",
                "title": "Example Com",
                "text": "Example Com text about dataset details.",
            },
        ]
        with patch.object(self.backend, "fetch_web_source_document", side_effect=documents), patch.object(
            self.backend,
            "call_hermes_messages",
            return_value=(json.dumps({"rows": [
                {"source_url": "https://example.org", "title": "Example Org", "summary": "overview"},
                {"source_url": "https://example.com", "title": "Example Com", "summary": "details"},
            ]}, ensure_ascii=False), {}),
        ):
            reply_text, meta = self.backend.execute_web_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "collection_execution_result")
        self.assertEqual(meta.get("downstream"), "chat:web_collection_result")
        attachments = meta.get("attachments") or []
        self.assertEqual(len(attachments), 1)
        attachment = attachments[0]
        self.assertTrue(Path(attachment.get("local_path")).exists())
        csv_text = Path(attachment.get("local_path")).read_text(encoding="utf-8")
        self.assertIn("title,summary,source_url", csv_text)
        self.assertIn("Example Org", csv_text)
        self.assertIn("Файл:", reply_text)

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

        documents = [
            {
                "requested_url": "https://legal.example/one",
                "final_url": "https://legal.example/one",
                "title": "Legal One",
                "text": "Legal One platform for contract review.",
            },
            {
                "requested_url": "https://legal.example/two",
                "final_url": "https://legal.example/two",
                "title": "Legal Two",
                "text": "Legal Two platform for legal workflow automation.",
            },
        ]
        llm_payload = {
            "reply_text": "Собрала данные и подготовила dashboard по теме LegalAI.",
            "dashboard": {
                "title": "LegalAI overview",
                "summary_cards": [{"label": "Компаний", "value": "2", "note": "demo"}],
                "sections": [{"title": "Сегменты", "items": [{"label": "Contract review", "value": "1"}, {"label": "Workflow", "value": "1"}]}],
                "sources": [{"label": "Legal One", "url": "https://legal.example/one"}],
            },
        }
        with patch.object(self.backend, "search_web_source_candidates", return_value=["https://legal.example/one", "https://legal.example/two"]), patch.object(
            self.backend,
            "fetch_web_source_document",
            side_effect=documents,
        ), patch.object(
            self.backend,
            "call_hermes_messages",
            side_effect=[
                (json.dumps({"rows": [
                    {"source_url": "https://legal.example/one", "компания": "Legal One", "type": "Contract review", "summary": "overview"},
                    {"source_url": "https://legal.example/two", "компания": "Legal Two", "type": "Workflow", "summary": "overview"},
                ]}, ensure_ascii=False), {}),
                (json.dumps(llm_payload, ensure_ascii=False), {}),
            ],
        ):
            reply_text, meta = self.backend.execute_web_collection_contract(contract)
        self.assertEqual(meta.get("message_kind"), "dashboard_result")
        self.assertEqual(meta.get("dashboard_builder"), "collection_execution_dashboard")
        self.assertTrue((meta.get("downstream") or "").startswith("dashboard:"))
        self.assertEqual((meta.get("dashboard") or {}).get("kind"), "external_research_dashboard")
        self.assertGreaterEqual(len((meta.get("dashboard") or {}).get("sections") or []), 1)
        self.assertIn("dashboard", reply_text.lower())

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

    def test_build_web_search_queries_expands_camelcase_subject(self):
        contract = {"subject": "LegalAI", "fields": ["компания", "продукт", "ссылка"]}
        queries = self.backend.build_web_search_queries(contract)
        self.assertIn("LegalAI", queries)
        self.assertIn('"LegalAI" OR "Legal AI"', queries)
        self.assertTrue(any("company product software" in item for item in queries))

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

        with patch.object(self.backend.urllib.request, "urlopen", side_effect=[DummyResponse(ddg_html), DummyResponse(bing_html)]):
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


if __name__ == "__main__":
    unittest.main()
