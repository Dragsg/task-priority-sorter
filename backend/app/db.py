from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from config import Config


@contextmanager
def get_connection():
    if not Config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing from backend/.env")

    with psycopg.connect(Config.DATABASE_URL, row_factory=dict_row) as connection:
        yield connection


def ensure_gmail_link_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_links (
                    user_id INTEGER PRIMARY KEY,
                    email_address TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    token_expiry TIMESTAMPTZ,
                    history_id TEXT,
                    linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        connection.commit()


def get_gmail_link(user_id: int):
    ensure_gmail_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    email_address,
                    access_token,
                    refresh_token,
                    token_expiry,
                    history_id,
                    linked_at,
                    updated_at
                FROM gmail_links
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return cursor.fetchone()


def save_gmail_link(
    user_id: int,
    email_address: str,
    access_token: str,
    refresh_token: str | None,
    token_expiry,
    history_id: str | None,
):
    ensure_gmail_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO gmail_links (
                    user_id,
                    email_address,
                    access_token,
                    refresh_token,
                    token_expiry,
                    history_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    email_address = EXCLUDED.email_address,
                    access_token = EXCLUDED.access_token,
                    refresh_token = COALESCE(EXCLUDED.refresh_token, gmail_links.refresh_token),
                    token_expiry = EXCLUDED.token_expiry,
                    history_id = COALESCE(EXCLUDED.history_id, gmail_links.history_id),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    email_address,
                    access_token,
                    refresh_token,
                    token_expiry,
                    history_id,
                ),
            )
        connection.commit()


def update_gmail_history(user_id: int, history_id: str):
    ensure_gmail_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE gmail_links
                SET history_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                """,
                (history_id, user_id),
            )
        connection.commit()
