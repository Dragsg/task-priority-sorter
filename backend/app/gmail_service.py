from datetime import datetime, timezone
from email.utils import parseaddr
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Config
from .db import get_gmail_link, save_gmail_link, save_messages, update_gmail_history

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
logger = logging.getLogger(__name__)


def normalize_expiry(expiry):
    if not expiry:
        return None

    if expiry.tzinfo is None:
        return expiry

    return expiry.astimezone(timezone.utc).replace(tzinfo=None)


def build_google_flow() -> Flow:
    if not Config.GOOGLE_CLIENT_ID or not Config.GOOGLE_CLIENT_SECRET:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required in backend/.env"
        )

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": Config.GOOGLE_CLIENT_ID,
                "client_secret": Config.GOOGLE_CLIENT_SECRET,
                "auth_uri": GOOGLE_AUTH_URI,
                "token_uri": GOOGLE_TOKEN_URI,
            }
        },
        scopes=Config.GMAIL_SCOPES,
    )
    flow.redirect_uri = Config.GOOGLE_REDIRECT_URI
    return flow


def build_credentials(user_id: int) -> Credentials:
    link = get_gmail_link(user_id)

    if not link:
        logger.info("No saved Gmail link available for user_id=%s", user_id)
        raise RuntimeError("No Gmail account is linked for this user yet.")

    expiry = normalize_expiry(link["token_expiry"])

    credentials = Credentials(
        token=link["access_token"],
        refresh_token=link["refresh_token"],
        token_uri=GOOGLE_TOKEN_URI,
        client_id=Config.GOOGLE_CLIENT_ID,
        client_secret=Config.GOOGLE_CLIENT_SECRET,
        scopes=Config.GMAIL_SCOPES,
        expiry=expiry,
    )

    if credentials.expired and credentials.refresh_token:
        logger.info("Refreshing expired Gmail token for user_id=%s", user_id)
        credentials.refresh(Request())
        save_gmail_link(
            user_id=user_id,
            email_address=link["email_address"],
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            token_expiry=normalize_expiry(credentials.expiry),
            history_id=link["history_id"],
        )
        logger.info("Refreshed Gmail token for user_id=%s", user_id)

    return credentials


def build_gmail_client(user_id: int):
    credentials = build_credentials(user_id)
    return build("gmail", "v1", credentials=credentials)


def get_header_map(message: dict) -> dict:
    return {
        header["name"].lower(): header["value"]
        for header in message.get("payload", {}).get("headers", [])
    }


def decode_base64url(value: str | None) -> str:
    if not value:
        return ""

    padding = "=" * (-len(value) % 4)
    try:
        import base64

        return base64.urlsafe_b64decode(f"{value}{padding}").decode(
            "utf-8",
            errors="replace",
        )
    except Exception:
        return ""


def extract_body_and_parts(payload: dict | None):
    text_segments = []
    mime_parts = []
    body_html_present = False
    attachments_present = False

    def walk(part: dict):
        nonlocal body_html_present, attachments_present

        mime_type = part.get("mimeType")
        body = part.get("body", {})
        filename = part.get("filename") or ""
        data = body.get("data")
        attachment_id = body.get("attachmentId")

        mime_parts.append(
            {
                "mimeType": mime_type,
                "filename": filename,
                "attachmentId": attachment_id,
                "size": body.get("size"),
            }
        )

        if attachment_id or filename:
            attachments_present = True

        if mime_type == "text/plain" and data:
            text_segments.append(decode_base64url(data))
        elif mime_type == "text/html" and data:
            body_html_present = True

        for child in part.get("parts", []) or []:
            walk(child)

    if payload:
        walk(payload)

    body_text = "\n".join(segment.strip() for segment in text_segments if segment.strip())
    return body_text, body_html_present, attachments_present, mime_parts


def parse_sender(raw_value: str):
    display_name, email_address = parseaddr(raw_value or "")
    sender_domain = email_address.split("@", 1)[1].lower() if "@" in email_address else None
    return display_name or None, email_address or None, sender_domain


def format_message(message: dict) -> dict:
    headers = get_header_map(message)

    internal_date = message.get("internalDate")
    received_at = None
    if internal_date:
        received_at = datetime.fromtimestamp(
            int(internal_date) / 1000,
            tz=timezone.utc,
        ).isoformat()

    return {
        "id": message["id"],
        "threadId": message.get("threadId"),
        "historyId": message.get("historyId"),
        "snippet": message.get("snippet", ""),
        "subject": headers.get("subject", "(no subject)"),
        "from": headers.get("from", "(unknown sender)"),
        "date": headers.get("date", ""),
        "receivedAt": received_at,
    }


def map_gmail_message_for_storage(message: dict) -> dict:
    headers = get_header_map(message)
    sender_display, sender_email, sender_domain = parse_sender(headers.get("from", ""))
    body_text, body_html_present, attachments_present, mime_parts = extract_body_and_parts(
        message.get("payload")
    )

    internal_date = message.get("internalDate")
    timestamp_iso = None
    if internal_date:
        timestamp_iso = datetime.fromtimestamp(
            int(internal_date) / 1000,
            tz=timezone.utc,
        )

    return {
        "platform": "gmail",
        "source_id": message["id"],
        "thread_id": message.get("threadId"),
        "timestamp_iso": timestamp_iso,
        "label_ids": message.get("labelIds", []),
        "sender_id": headers.get("message-id"),
        "sender_display": sender_display,
        "sender_email": sender_email,
        "sender_domain": sender_domain,
        "subject": headers.get("subject") or "(no subject)",
        "snippet": message.get("snippet", ""),
        "body_text": body_text,
        "body_html_present": body_html_present,
        "attachments_present": attachments_present,
        "mime_parts": mime_parts,
        "provider_metadata": {
            "historyId": message.get("historyId"),
            "internalDate": internal_date,
            "sizeEstimate": message.get("sizeEstimate"),
            "payloadMimeType": message.get("payload", {}).get("mimeType"),
        },
        "from_raw": headers.get("from"),
        "to_raw": headers.get("to"),
        "cc_raw": headers.get("cc"),
        "bcc_raw": headers.get("bcc"),
    }


def get_message_detail(service, message_id: str) -> dict:
    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    return message


def list_recent_messages(user_id: int, limit: int = 5) -> dict:
    service = build_gmail_client(user_id)
    response = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], maxResults=limit)
        .execute()
    )

    detailed_messages = [
        get_message_detail(service, item["id"]) for item in response.get("messages", [])
    ]
    save_messages(
        user_id,
        [map_gmail_message_for_storage(message) for message in detailed_messages],
    )
    messages = [format_message(message) for message in detailed_messages]

    latest_history_id = messages[0]["historyId"] if messages else None
    if latest_history_id:
        update_gmail_history(user_id, latest_history_id)

    return {
        "messages": messages,
        "historyId": latest_history_id,
    }


def list_new_messages(user_id: int) -> dict:
    link = get_gmail_link(user_id)
    if not link:
        raise RuntimeError("No Gmail account is linked for this user yet.")

    if not link["history_id"]:
        return {"messages": [], "historyId": None}

    service = build_gmail_client(user_id)

    try:
        response = (
            service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=link["history_id"],
                historyTypes=["messageAdded"],
            )
            .execute()
        )
    except HttpError as error:
        if getattr(error.resp, "status", None) == 404:
            raise RuntimeError(
                "Gmail history expired. Load the latest 5 emails again to reset sync."
            ) from error
        raise

    message_ids = []
    seen_ids = set()
    for history_item in response.get("history", []):
        for added in history_item.get("messagesAdded", []):
            message = added.get("message", {})
            message_id = message.get("id")
            if message_id and message_id not in seen_ids:
                seen_ids.add(message_id)
                message_ids.append(message_id)

    detailed_messages = [get_message_detail(service, message_id) for message_id in message_ids]
    save_messages(
        user_id,
        [map_gmail_message_for_storage(message) for message in detailed_messages],
    )
    messages = [format_message(message) for message in detailed_messages]
    messages.sort(key=lambda item: item.get("receivedAt") or "", reverse=True)

    new_history_id = response.get("historyId") or link["history_id"]
    update_gmail_history(user_id, new_history_id)

    return {
        "messages": messages,
        "historyId": new_history_id,
    }


def complete_gmail_link(user_id: int, flow: Flow):
    credentials = flow.credentials
    service = build("gmail", "v1", credentials=credentials)

    profile = service.users().getProfile(userId="me").execute()
    recent_messages = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], maxResults=5)
        .execute()
    )
    recent_message_ids = recent_messages.get("messages", [])

    latest_history_id = None
    if recent_message_ids:
        latest_message = get_message_detail(service, recent_message_ids[0]["id"])
        latest_history_id = latest_message.get("historyId")

    save_gmail_link(
        user_id=user_id,
        email_address=profile["emailAddress"],
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
        token_expiry=normalize_expiry(credentials.expiry),
        history_id=latest_history_id,
    )

    logger.info(
        "Completed Gmail link for user_id=%s email_address=%s",
        user_id,
        profile["emailAddress"],
    )

    return profile["emailAddress"]
