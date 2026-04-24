import logging
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, TypeAlias, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config import Config
from .time_utils import now_sgt

logger = logging.getLogger(__name__)
DATABASE_TIMEZONE = "Asia/Singapore"
DbRow: TypeAlias = dict[str, Any]


@contextmanager
def get_connection():
    if not Config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing from backend/.env")

    with psycopg.connect(
        Config.DATABASE_URL,
        row_factory=cast(Any, dict_row),
        options=f"-c timezone={DATABASE_TIMEZONE}",
    ) as connection:
        yield connection


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def ensure_stored_emails_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS stored_emails (
                    id BIGSERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    thread_id TEXT,
                    timestamp_iso TIMESTAMPTZ,
                    label_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    sender_id TEXT,
                    sender_display TEXT,
                    sender_email TEXT,
                    sender_domain TEXT,
                    subject TEXT,
                    snippet TEXT,
                    body_text TEXT NOT NULL DEFAULT '',
                    body_html_present BOOLEAN NOT NULL DEFAULT FALSE,
                    attachments_present BOOLEAN NOT NULL DEFAULT FALSE,
                    mime_parts JSONB NOT NULL DEFAULT '[]'::jsonb,
                    provider_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    from_raw TEXT,
                    to_raw TEXT,
                    cc_raw TEXT,
                    bcc_raw TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, platform, source_id)
                )
                """
            )
        connection.commit()


def _message_to_dict(message):
    if hasattr(message, "model_dump"):
        return message.model_dump()

    if isinstance(message, dict):
        return dict(message)

    raise TypeError("save_messages expects dicts or objects with model_dump()")


def save_messages(user_id: int, messages: list):
    ensure_stored_emails_table()

    normalized_messages = [_message_to_dict(message) for message in messages]
    if not normalized_messages:
        return

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for message in normalized_messages:
                cursor.execute(
                    """
                    INSERT INTO stored_emails (
                        user_id,
                        platform,
                        source_id,
                        thread_id,
                        timestamp_iso,
                        label_ids,
                        sender_id,
                        sender_display,
                        sender_email,
                        sender_domain,
                        subject,
                        snippet,
                        body_text,
                        body_html_present,
                        attachments_present,
                        mime_parts,
                        provider_metadata,
                        from_raw,
                        to_raw,
                        cc_raw,
                        bcc_raw
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (user_id, platform, source_id) DO UPDATE SET
                        thread_id = EXCLUDED.thread_id,
                        timestamp_iso = EXCLUDED.timestamp_iso,
                        label_ids = EXCLUDED.label_ids,
                        sender_id = EXCLUDED.sender_id,
                        sender_display = EXCLUDED.sender_display,
                        sender_email = EXCLUDED.sender_email,
                        sender_domain = EXCLUDED.sender_domain,
                        subject = EXCLUDED.subject,
                        snippet = EXCLUDED.snippet,
                        body_text = EXCLUDED.body_text,
                        body_html_present = EXCLUDED.body_html_present,
                        attachments_present = EXCLUDED.attachments_present,
                        mime_parts = EXCLUDED.mime_parts,
                        provider_metadata = EXCLUDED.provider_metadata,
                        from_raw = EXCLUDED.from_raw,
                        to_raw = EXCLUDED.to_raw,
                        cc_raw = EXCLUDED.cc_raw,
                        bcc_raw = EXCLUDED.bcc_raw,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        user_id,
                        message.get("platform"),
                        message.get("source_id"),
                        message.get("thread_id"),
                        message.get("timestamp_iso"),
                        Jsonb(message.get("label_ids") or []),
                        message.get("sender_id"),
                        message.get("sender_display"),
                        message.get("sender_email"),
                        message.get("sender_domain"),
                        message.get("subject"),
                        message.get("snippet"),
                        message.get("body_text") or "",
                        bool(message.get("body_html_present")),
                        bool(message.get("attachments_present")),
                        Jsonb(message.get("mime_parts") or []),
                        Jsonb(message.get("provider_metadata") or {}),
                        message.get("from_raw"),
                        message.get("to_raw"),
                        message.get("cc_raw"),
                        message.get("bcc_raw"),
                    ),
                )
        connection.commit()

    logger.info(
        "Saved %s messages into stored_emails for user_id=%s",
        len(normalized_messages),
        user_id,
    )


def list_stored_messages(user_id: int, limit: int | None = None) -> list[DbRow]:
    ensure_stored_emails_table()

    query = """
        SELECT
            user_id,
            platform,
            source_id,
            thread_id,
            timestamp_iso,
            label_ids,
            sender_id,
            sender_display,
            sender_email,
            sender_domain,
            subject,
            snippet,
            body_text,
            body_html_present,
            attachments_present,
            mime_parts,
            provider_metadata,
            from_raw,
            to_raw,
            cc_raw,
            bcc_raw
        FROM stored_emails
        WHERE user_id = %s
        ORDER BY COALESCE(timestamp_iso, created_at) DESC, id DESC
    """
    params: list[object] = [user_id]
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cast(list[DbRow], cursor.fetchall())

    return rows


def list_task_card_payloads(user_id: int) -> list[DbRow]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    task_id,
                    user_id,
                    payload,
                    created_at
                FROM task_cards
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (str(user_id),),
            )
            rows = cast(list[DbRow], cursor.fetchall())

    payloads = []
    for row in rows:
        payload = dict(row.get("payload") or {})
        payload.setdefault("task_id", row["task_id"])
        payload.setdefault("user_id", row["user_id"])
        payload["created_at"] = (
            row["created_at"].isoformat() if row.get("created_at") else None
        )
        payloads.append(payload)

    return payloads


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


def get_gmail_link(user_id: int) -> DbRow | None:
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
            link = cast(DbRow | None, cursor.fetchone())

    if link:
        logger.info(
            "Found saved Gmail link for user_id=%s email_address=%s",
            user_id,
            link["email_address"],
        )
    else:
        logger.info("No Gmail link exists for user_id=%s", user_id)

    return link


def list_gmail_link_user_ids() -> list[int]:
    ensure_gmail_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id
                FROM gmail_links
                ORDER BY user_id
                """
            )
            rows = cast(list[DbRow], cursor.fetchall())

    return [row["user_id"] for row in rows]


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

    logger.info(
        "Saved Gmail link for user_id=%s email_address=%s history_id=%s",
        user_id,
        email_address,
        history_id,
    )


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

    logger.info(
        "Updated Gmail history for user_id=%s history_id=%s",
        user_id,
        history_id,
    )


def ensure_outlook_link_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS outlook_links (
                    user_id INTEGER PRIMARY KEY,
                    email_address TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    token_expiry TIMESTAMPTZ,
                    last_received_at TIMESTAMPTZ,
                    linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        connection.commit()


def get_outlook_link(user_id: int) -> DbRow | None:
    ensure_outlook_link_table()

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
                    last_received_at,
                    linked_at,
                    updated_at
                FROM outlook_links
                WHERE user_id = %s
                """,
                (user_id,),
            )
            link = cast(DbRow | None, cursor.fetchone())

    if link:
        logger.info(
            "Found saved Outlook link for user_id=%s email_address=%s",
            user_id,
            link["email_address"],
        )
    else:
        logger.info("No Outlook link exists for user_id=%s", user_id)

    return link


def list_outlook_link_user_ids() -> list[int]:
    ensure_outlook_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id
                FROM outlook_links
                ORDER BY user_id
                """
            )
            rows = cast(list[DbRow], cursor.fetchall())

    return [row["user_id"] for row in rows]


def save_outlook_link(
    user_id: int,
    email_address: str,
    access_token: str,
    refresh_token: str | None,
    token_expiry,
    last_received_at,
):
    ensure_outlook_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO outlook_links (
                    user_id,
                    email_address,
                    access_token,
                    refresh_token,
                    token_expiry,
                    last_received_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    email_address = EXCLUDED.email_address,
                    access_token = EXCLUDED.access_token,
                    refresh_token = COALESCE(EXCLUDED.refresh_token, outlook_links.refresh_token),
                    token_expiry = EXCLUDED.token_expiry,
                    last_received_at = COALESCE(EXCLUDED.last_received_at, outlook_links.last_received_at),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    email_address,
                    access_token,
                    refresh_token,
                    token_expiry,
                    last_received_at,
                ),
            )
        connection.commit()

    logger.info(
        "Saved Outlook link for user_id=%s email_address=%s last_received_at=%s",
        user_id,
        email_address,
        last_received_at,
    )


def update_outlook_last_received_at(user_id: int, last_received_at):
    ensure_outlook_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outlook_links
                SET last_received_at = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                """,
                (last_received_at, user_id),
            )
        connection.commit()

    logger.info(
        "Updated Outlook sync cursor for user_id=%s last_received_at=%s",
        user_id,
        last_received_at,
    )


def ensure_user_details_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS public.user_details (
                    user_id BIGSERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    preferences TEXT,
                    performance_time TEXT,
                    important_topic TEXT,
                    prioritise_by TEXT
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.user_details
                ADD COLUMN IF NOT EXISTS username TEXT,
                ADD COLUMN IF NOT EXISTS password TEXT,
                ADD COLUMN IF NOT EXISTS preferences TEXT,
                ADD COLUMN IF NOT EXISTS performance_time TEXT,
                ADD COLUMN IF NOT EXISTS important_topic TEXT,
                ADD COLUMN IF NOT EXISTS prioritise_by TEXT
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.user_details
                DROP COLUMN IF EXISTS name
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS user_details_username_key
                ON public.user_details (username)
                """
            )
        connection.commit()


def get_user_by_username(username: str):
    ensure_user_details_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    username,
                    password,
                    preferences,
                    performance_time,
                    important_topic,
                    prioritise_by
                FROM public.user_details
                WHERE username = %s
                """,
                (username,),
            )
            return cast(DbRow | None, cursor.fetchone())


def get_user_by_id(user_id: int) -> DbRow | None:
    ensure_user_details_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    username,
                    preferences,
                    performance_time,
                    important_topic,
                    prioritise_by
                FROM public.user_details
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return cast(DbRow | None, cursor.fetchone())


def create_user(username: str, password_hash: str) -> DbRow:
    ensure_user_details_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.user_details (username, password)
                VALUES (%s, %s)
                RETURNING
                    user_id,
                    username,
                    preferences,
                    performance_time,
                    important_topic,
                    prioritise_by
                """,
                (username, password_hash),
            )
            user = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    if user is None:
        raise LookupError("Failed to create user.")

    logger.info("Created user_details row for user_id=%s username=%s", user["user_id"], username)
    return user


def update_user_preferences(user_id: int, preferences: str) -> DbRow:
    ensure_user_details_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.user_details
                SET preferences = %s
                WHERE user_id = %s
                RETURNING
                    user_id,
                    username,
                    preferences,
                    performance_time,
                    important_topic,
                    prioritise_by
                """,
                (preferences, user_id),
            )
            user = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    if user is None:
        raise LookupError(f"User not found for user_id={user_id}")

    logger.info(
        "Updated onboarding preferences for user_id=%s preferences=%s",
        user_id,
        preferences,
    )
    return user


def update_user_username(user_id: int, username: str) -> DbRow | None:
    ensure_user_details_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.user_details
                SET username = %s
                WHERE user_id = %s
                RETURNING
                    user_id,
                    username,
                    preferences,
                    performance_time,
                    important_topic,
                    prioritise_by
                """,
                (username, user_id),
            )
            user = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    if user:
        logger.info("Updated username for user_id=%s username=%s", user_id, username)

    return user


def update_user_onboarding_answers(
    user_id: int,
    *,
    performance_time: str,
    important_topic: str,
    prioritise_by: str,
) -> DbRow | None:
    ensure_user_details_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.user_details
                SET performance_time = %s,
                    important_topic = %s,
                    prioritise_by = %s
                WHERE user_id = %s
                RETURNING
                    user_id,
                    username,
                    preferences,
                    performance_time,
                    important_topic,
                    prioritise_by
                """,
                (performance_time, important_topic, prioritise_by, user_id),
            )
            user = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    logger.info(
        "Updated onboarding answers for user_id=%s performance_time=%s important_topic=%s prioritise_by=%s",
        user_id,
        performance_time,
        important_topic,
        prioritise_by,
    )
    return user


def delete_user_account(user_id: int) -> None:
    ensure_user_details_table()
    ensure_gmail_link_table()
    ensure_outlook_link_table()
    ensure_stored_emails_table()

    deleted_tables: list[str] = []
    user_id_text = str(user_id)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT columns.table_schema, columns.table_name
                FROM information_schema.columns AS columns
                INNER JOIN information_schema.tables AS tables
                    ON tables.table_schema = columns.table_schema
                   AND tables.table_name = columns.table_name
                WHERE columns.table_schema = 'public'
                  AND columns.column_name = 'user_id'
                  AND tables.table_type = 'BASE TABLE'
                ORDER BY CASE WHEN columns.table_name = 'user_details' THEN 1 ELSE 0 END, columns.table_name
                """
            )
            table_rows = cast(list[DbRow], cursor.fetchall())

            for row in table_rows:
                table_schema = str(row["table_schema"])
                table_name = str(row["table_name"])
                qualified_table = f"{_quote_identifier(table_schema)}.{_quote_identifier(table_name)}"
                if table_name == "user_details":
                    cursor.execute(
                        f"DELETE FROM {qualified_table} WHERE user_id = %s",
                        (user_id,),
                    )
                else:
                    cursor.execute(
                        f"DELETE FROM {qualified_table} WHERE CAST(user_id AS TEXT) = %s",
                        (user_id_text,),
                    )
                if cursor.rowcount:
                    deleted_tables.append(f"{table_schema}.{table_name}")
        connection.commit()

    logger.info(
        "Deleted account data for user_id=%s across tables=%s",
        user_id,
        ", ".join(deleted_tables) if deleted_tables else "none",
    )


def ensure_telegram_link_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_links (
                    user_id INTEGER PRIMARY KEY,
                    telegram_chat_id TEXT NOT NULL UNIQUE,
                    telegram_chat_type TEXT,
                    telegram_username TEXT,
                    telegram_display_name TEXT,
                    linked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        connection.commit()


def ensure_telegram_link_codes_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_link_codes (
                    code TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    claimed_chat_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMPTZ NOT NULL,
                    claimed_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_telegram_link_codes_user_id
                ON telegram_link_codes (user_id)
                """
            )
        connection.commit()


def ensure_telegram_notification_settings_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_notification_settings (
                    user_id INTEGER PRIMARY KEY,
                    telegram_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    alert_critical BOOLEAN NOT NULL DEFAULT TRUE,
                    alert_high BOOLEAN NOT NULL DEFAULT TRUE,
                    alert_medium BOOLEAN NOT NULL DEFAULT FALSE,
                    alert_low BOOLEAN NOT NULL DEFAULT FALSE,
                    daily_digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    daily_digest_time TEXT NOT NULL DEFAULT '08:00',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        connection.commit()


def ensure_telegram_alert_logs_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_alert_logs (
                    id BIGSERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    canonical_task_id TEXT NOT NULL,
                    alert_kind TEXT NOT NULL DEFAULT 'instant',
                    priority_tier TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    telegram_message_id TEXT,
                    task_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMPTZ,
                    UNIQUE (user_id, canonical_task_id, alert_kind)
                )
                """
            )
        connection.commit()


def ensure_telegram_digest_logs_table():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_digest_logs (
                    id BIGSERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    digest_date DATE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    telegram_message_id TEXT,
                    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMPTZ,
                    UNIQUE (user_id, digest_date)
                )
                """
            )
        connection.commit()


def ensure_telegram_tables():
    ensure_telegram_link_table()
    ensure_telegram_link_codes_table()
    ensure_telegram_notification_settings_table()
    ensure_telegram_alert_logs_table()
    ensure_telegram_digest_logs_table()


def get_telegram_link(user_id: int) -> DbRow | None:
    ensure_telegram_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    telegram_chat_id,
                    telegram_chat_type,
                    telegram_username,
                    telegram_display_name,
                    linked_at,
                    updated_at
                FROM telegram_links
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return cast(DbRow | None, cursor.fetchone())


def list_telegram_link_user_ids() -> list[int]:
    ensure_telegram_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id
                FROM telegram_links
                ORDER BY user_id
                """
            )
            rows = cast(list[DbRow], cursor.fetchall())

    return [int(row["user_id"]) for row in rows]


def save_telegram_link(
    user_id: int,
    *,
    chat_id: str,
    chat_type: str | None,
    chat_username: str | None,
    chat_display_name: str | None,
) -> DbRow:
    ensure_telegram_link_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO telegram_links (
                    user_id,
                    telegram_chat_id,
                    telegram_chat_type,
                    telegram_username,
                    telegram_display_name
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    telegram_chat_id = EXCLUDED.telegram_chat_id,
                    telegram_chat_type = EXCLUDED.telegram_chat_type,
                    telegram_username = EXCLUDED.telegram_username,
                    telegram_display_name = EXCLUDED.telegram_display_name,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING
                    user_id,
                    telegram_chat_id,
                    telegram_chat_type,
                    telegram_username,
                    telegram_display_name,
                    linked_at,
                    updated_at
                """,
                (user_id, chat_id, chat_type, chat_username, chat_display_name),
            )
            row = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    if row is None:
        raise LookupError(f"Failed to save Telegram link for user_id={user_id}")

    logger.info("Saved Telegram link for user_id=%s chat_id=%s", user_id, chat_id)
    return row


def delete_telegram_link(user_id: int) -> None:
    ensure_telegram_tables()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM telegram_links
                WHERE user_id = %s
                """,
                (user_id,),
            )
            cursor.execute(
                """
                DELETE FROM telegram_link_codes
                WHERE user_id = %s
                """,
                (user_id,),
            )
        connection.commit()


def create_telegram_link_code(user_id: int, code: str, expires_at: datetime) -> DbRow:
    ensure_telegram_link_codes_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM telegram_link_codes
                WHERE user_id = %s
                  AND claimed_at IS NULL
                """,
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO telegram_link_codes (
                    code,
                    user_id,
                    expires_at
                )
                VALUES (%s, %s, %s)
                RETURNING code, user_id, created_at, expires_at, claimed_at
                """,
                (code, user_id, expires_at),
            )
            row = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    if row is None:
        raise LookupError(f"Failed to create Telegram link code for user_id={user_id}")

    logger.info("Created Telegram link code for user_id=%s code=%s", user_id, code)
    return row


def get_active_telegram_link_code(user_id: int, *, now: datetime | None = None) -> DbRow | None:
    ensure_telegram_link_codes_table()
    current_time = now or now_sgt()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT code, user_id, created_at, expires_at, claimed_at
                FROM telegram_link_codes
                WHERE user_id = %s
                  AND claimed_at IS NULL
                  AND expires_at > %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, current_time),
            )
            return cast(DbRow | None, cursor.fetchone())


def consume_telegram_link_code(
    code: str,
    *,
    chat_id: str,
    chat_type: str | None,
    chat_username: str | None,
    chat_display_name: str | None,
    now: datetime | None = None,
) -> DbRow:
    ensure_telegram_tables()
    current_time = now or now_sgt()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT code, user_id, expires_at, claimed_at
                FROM telegram_link_codes
                WHERE code = %s
                FOR UPDATE
                """,
                (code,),
            )
            code_row = cast(DbRow | None, cursor.fetchone())
            if code_row is None:
                raise LookupError("This linking code is invalid.")
            if code_row.get("claimed_at") is not None:
                raise ValueError("This linking code has already been used.")
            if code_row["expires_at"] <= current_time:
                raise ValueError("This linking code has expired. Generate a new one in the app.")

            cursor.execute(
                """
                SELECT user_id
                FROM telegram_links
                WHERE telegram_chat_id = %s
                FOR UPDATE
                """,
                (chat_id,),
            )
            existing_link = cast(DbRow | None, cursor.fetchone())
            if existing_link and int(existing_link["user_id"]) != int(code_row["user_id"]):
                raise ValueError("This Telegram chat is already linked to a different account.")

            cursor.execute(
                """
                INSERT INTO telegram_links (
                    user_id,
                    telegram_chat_id,
                    telegram_chat_type,
                    telegram_username,
                    telegram_display_name
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    telegram_chat_id = EXCLUDED.telegram_chat_id,
                    telegram_chat_type = EXCLUDED.telegram_chat_type,
                    telegram_username = EXCLUDED.telegram_username,
                    telegram_display_name = EXCLUDED.telegram_display_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(code_row["user_id"]),
                    chat_id,
                    chat_type,
                    chat_username,
                    chat_display_name,
                ),
            )
            cursor.execute(
                """
                UPDATE telegram_link_codes
                SET claimed_chat_id = %s,
                    claimed_at = CURRENT_TIMESTAMP
                WHERE code = %s
                RETURNING code, user_id, expires_at, claimed_at
                """,
                (chat_id, code),
            )
            consumed_row = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    if consumed_row is None:
        raise LookupError("Failed to claim Telegram linking code.")

    logger.info(
        "Consumed Telegram link code for user_id=%s chat_id=%s",
        consumed_row["user_id"],
        chat_id,
    )
    return consumed_row


def get_telegram_notification_settings(user_id: int) -> DbRow:
    ensure_telegram_notification_settings_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    telegram_enabled,
                    alert_critical,
                    alert_high,
                    alert_medium,
                    alert_low,
                    daily_digest_enabled,
                    daily_digest_time,
                    updated_at
                FROM telegram_notification_settings
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cast(DbRow | None, cursor.fetchone())

    if row is not None:
        return row

    return {
        "user_id": user_id,
        "telegram_enabled": True,
        "alert_critical": True,
        "alert_high": True,
        "alert_medium": False,
        "alert_low": False,
        "daily_digest_enabled": True,
        "daily_digest_time": "08:00",
        "updated_at": None,
    }


def save_telegram_notification_settings(
    user_id: int,
    *,
    telegram_enabled: bool,
    alert_critical: bool,
    alert_high: bool,
    alert_medium: bool,
    alert_low: bool,
    daily_digest_enabled: bool,
    daily_digest_time: str,
) -> DbRow:
    ensure_telegram_notification_settings_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO telegram_notification_settings (
                    user_id,
                    telegram_enabled,
                    alert_critical,
                    alert_high,
                    alert_medium,
                    alert_low,
                    daily_digest_enabled,
                    daily_digest_time
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    telegram_enabled = EXCLUDED.telegram_enabled,
                    alert_critical = EXCLUDED.alert_critical,
                    alert_high = EXCLUDED.alert_high,
                    alert_medium = EXCLUDED.alert_medium,
                    alert_low = EXCLUDED.alert_low,
                    daily_digest_enabled = EXCLUDED.daily_digest_enabled,
                    daily_digest_time = EXCLUDED.daily_digest_time,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING
                    user_id,
                    telegram_enabled,
                    alert_critical,
                    alert_high,
                    alert_medium,
                    alert_low,
                    daily_digest_enabled,
                    daily_digest_time,
                    updated_at
                """,
                (
                    user_id,
                    telegram_enabled,
                    alert_critical,
                    alert_high,
                    alert_medium,
                    alert_low,
                    daily_digest_enabled,
                    daily_digest_time,
                ),
            )
            row = cast(DbRow | None, cursor.fetchone())
        connection.commit()

    if row is None:
        raise LookupError(f"Failed to save Telegram settings for user_id={user_id}")

    logger.info("Saved Telegram notification settings for user_id=%s", user_id)
    return row


def claim_telegram_alert(
    user_id: int,
    *,
    canonical_task_id: str,
    priority_tier: str | None,
    task_payload: dict,
) -> bool:
    ensure_telegram_alert_logs_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO telegram_alert_logs (
                    user_id,
                    canonical_task_id,
                    priority_tier,
                    status,
                    task_snapshot
                )
                VALUES (%s, %s, %s, 'pending', %s)
                ON CONFLICT (user_id, canonical_task_id, alert_kind) DO NOTHING
                """,
                (
                    user_id,
                    canonical_task_id,
                    priority_tier,
                    Jsonb(task_payload),
                ),
            )
            inserted = cursor.rowcount > 0
        connection.commit()

    return inserted


def mark_telegram_alert_sent(
    user_id: int,
    *,
    canonical_task_id: str,
    message_id: str | None,
) -> None:
    ensure_telegram_alert_logs_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE telegram_alert_logs
                SET status = 'sent',
                    telegram_message_id = %s,
                    sent_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                  AND canonical_task_id = %s
                  AND alert_kind = 'instant'
                """,
                (message_id, user_id, canonical_task_id),
            )
        connection.commit()


def clear_telegram_alert_claim(user_id: int, *, canonical_task_id: str) -> None:
    ensure_telegram_alert_logs_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM telegram_alert_logs
                WHERE user_id = %s
                  AND canonical_task_id = %s
                  AND alert_kind = 'instant'
                  AND status = 'pending'
                """,
                (user_id, canonical_task_id),
            )
        connection.commit()


def claim_telegram_digest(user_id: int, *, digest_date: date) -> bool:
    ensure_telegram_digest_logs_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO telegram_digest_logs (
                    user_id,
                    digest_date,
                    status
                )
                VALUES (%s, %s, 'pending')
                ON CONFLICT (user_id, digest_date) DO NOTHING
                """,
                (user_id, digest_date),
            )
            inserted = cursor.rowcount > 0
        connection.commit()

    return inserted


def mark_telegram_digest_sent(
    user_id: int,
    *,
    digest_date: date,
    message_id: str | None,
    summary: dict | None = None,
) -> None:
    ensure_telegram_digest_logs_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE telegram_digest_logs
                SET status = 'sent',
                    telegram_message_id = %s,
                    summary = %s,
                    sent_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                  AND digest_date = %s
                """,
                (
                    message_id,
                    Jsonb(summary or {}),
                    user_id,
                    digest_date,
                ),
            )
        connection.commit()


def clear_telegram_digest_claim(user_id: int, *, digest_date: date) -> None:
    ensure_telegram_digest_logs_table()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM telegram_digest_logs
                WHERE user_id = %s
                  AND digest_date = %s
                  AND status = 'pending'
                """,
                (user_id, digest_date),
            )
        connection.commit()
