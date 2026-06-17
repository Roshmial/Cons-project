from __future__ import annotations

import os
from pathlib import Path

import duckdb
import psycopg

APP_DB_SCHEMA = os.getenv("HERMES_WEB_BACKEND_SCHEMA", "app")
DUCKDB_PATH = Path(os.getenv("HERMES_WEB_BACKEND_DB_PATH", Path(__file__).resolve().parent / "data" / "hermes_web_app.duckdb"))
POSTGRES_DSN = os.getenv("HERMES_WEB_BACKEND_DSN", "").strip()
BATCH_SIZE = max(100, int(os.getenv("HERMES_WEB_MIGRATION_BATCH_SIZE", "1000")))

SEQUENCE_TABLES = [
    "users", "threads", "messages", "user_files", "feedback", "chat_tasks", "jobs",
    "job_acl", "job_recipients", "job_subscriptions", "job_runs", "reference_catalogs",
    "reference_items", "user_change_log", "reference_item_change_log",
]


def qmarks(count: int) -> str:
    return ", ".join(["%s"] * count)


def main() -> None:
    if not POSTGRES_DSN:
        raise SystemExit("HERMES_WEB_BACKEND_DSN is required")
    if not DUCKDB_PATH.exists():
        raise SystemExit(f"DuckDB file not found: {DUCKDB_PATH}")

    src = duckdb.connect(str(DUCKDB_PATH))
    dst = psycopg.connect(POSTGRES_DSN, autocommit=False)
    try:
        with dst.cursor() as cur:
            cur.execute(f"SET search_path TO {APP_DB_SCHEMA}")

        tables = [
            row[0]
            for row in src.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = ? AND table_type = 'BASE TABLE'
                ORDER BY table_name ASC
                """,
                [APP_DB_SCHEMA],
            ).fetchall()
        ]
        if not tables:
            raise SystemExit(f"No tables found in schema {APP_DB_SCHEMA} inside {DUCKDB_PATH}")

        with dst.cursor() as cur:
            for table in tables:
                cur.execute(f'TRUNCATE TABLE {table} RESTART IDENTITY CASCADE')
        dst.commit()

        for table in tables:
            columns = [
                row[0]
                for row in src.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = ?
                    ORDER BY ordinal_position ASC
                    """,
                    [APP_DB_SCHEMA, table],
                ).fetchall()
            ]
            if not columns:
                continue
            column_list = ", ".join(columns)
            insert_sql = f"INSERT INTO {table} ({column_list}) VALUES ({qmarks(len(columns))})"
            total = 0
            offset = 0
            while True:
                rows = src.execute(
                    f"SELECT {column_list} FROM {APP_DB_SCHEMA}.{table} LIMIT ? OFFSET ?",
                    [BATCH_SIZE, offset],
                ).fetchall()
                if not rows:
                    break
                with dst.cursor() as cur:
                    cur.executemany(insert_sql, rows)
                dst.commit()
                total += len(rows)
                offset += len(rows)
                print(f"migrated {table}: {total}")

        with dst.cursor() as cur:
            for table in SEQUENCE_TABLES:
                cur.execute(
                    f"SELECT setval('{table}_id_seq', COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                )
        dst.commit()
        print("migration complete")
    finally:
        try:
            src.close()
        finally:
            dst.close()


if __name__ == "__main__":
    main()
