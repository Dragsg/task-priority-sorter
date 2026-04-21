import logging
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config import Config

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    if not Config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing from backend/.env")

    with psycopg.connect(Config.DATABASE_URL, row_factory=dict_row) as connection:
        yield connection


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
            link = cursor.fetchone()

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
            rows = cursor.fetchall()

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


def get_outlook_link(user_id: int):
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
            link = cursor.fetchone()

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
            rows = cursor.fetchall()

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


def get_user_by_email(email: str):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    name,
                    email,
                    password,
                    preferences
                FROM public.user_details
                WHERE email = %s
                """,
                (email,),
            )
            return cursor.fetchone()


def get_user_by_id(user_id: int):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    user_id,
                    name,
                    email,
                    password,
                    preferences
                FROM public.user_details
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return cursor.fetchone()


def create_user(name: str, email: str, password_hash: str):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.user_details (name, email, password)
                VALUES (%s, %s, %s)
                RETURNING
                    user_id,
                    name,
                    email,
                    password,
                    preferences
                """,
                (name, email, password_hash),
            )
            user = cursor.fetchone()
        connection.commit()

    logger.info("Created user_details row for user_id=%s email=%s", user["user_id"], email)
    return user


def update_user_preferences(user_id: int, preferences: str):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.user_details
                SET preferences = %s
                WHERE user_id = %s
                RETURNING
                    user_id,
                    name,
                    email,
                    password,
                    preferences
                """,
                (preferences, user_id),
            )
            user = cursor.fetchone()
        connection.commit()

    logger.info(
        "Updated onboarding preferences for user_id=%s preferences=%s",
        user_id,
        preferences,
    )
    return user
