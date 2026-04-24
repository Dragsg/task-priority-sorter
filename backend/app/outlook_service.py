import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config
from .db import (
    get_outlook_link,
    save_messages,
    save_outlook_link,
    update_outlook_last_received_at,
)
from .time_utils import to_sgt

logger = logging.getLogger(__name__)

MICROSOFT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
OUTLOOK_INBOX_MESSAGES_PATH = "/me/mailFolders/inbox/messages"


def normalize_expiry(expiry):
    if not expiry:
        return None

    if expiry.tzinfo is None:
        return expiry

    return expiry.astimezone(timezone.utc).replace(tzinfo=None)


def parse_graph_datetime(value: str | None):
    if not value:
        return None

    return to_sgt(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _require_outlook_link(user_id: int, link: dict | None = None) -> dict:
    resolved_link = link or get_outlook_link(user_id)
    if not resolved_link:
        logger.info("No saved Outlook link available for user_id=%s", user_id)
        raise RuntimeError("No Outlook account is linked for this user yet.")
    return resolved_link


def build_microsoft_authorize_url(state: str) -> str:
    if not Config.MICROSOFT_CLIENT_ID or not Config.MICROSOFT_CLIENT_SECRET:
        raise RuntimeError(
            "MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET are required in backend/.env"
        )

    base_url = (
        f"https://login.microsoftonline.com/"
        f"{Config.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
    )
    query = urlencode(
        {
            "client_id": Config.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": Config.MICROSOFT_REDIRECT_URI,
            "response_mode": "query",
            "scope": " ".join(Config.MICROSOFT_SCOPES),
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{base_url}?{query}"


def build_graph_url(path: str, params: dict | None = None) -> str:
    base_url = f"{MICROSOFT_GRAPH_BASE_URL}{path}"
    if not params:
        return base_url

    return f"{base_url}?{urlencode(params)}"


def microsoft_token_request(payload: dict) -> dict:
    token_url = (
        f"https://login.microsoftonline.com/"
        f"{Config.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"
    )
    encoded_payload = urlencode(payload).encode("utf-8")
    request = Request(
        token_url,
        data=encoded_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        logger.exception("Microsoft token request failed: %s", body)
        raise RuntimeError(body) from error


def graph_get_json(url: str, access_token: str) -> dict:
    logger.info("Outlook Graph GET %s", url)
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                logger.info(
                    "Outlook Graph response keys=%s value_count=%s",
                    sorted(payload.keys()),
                    len(payload.get("value", [])) if isinstance(payload.get("value"), list) else "n/a",
                )
            return payload
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        logger.exception("Microsoft Graph request failed: %s", body)
        raise RuntimeError(body) from error


def compute_expiry(expires_in: int | str | None):
    if not expires_in:
        return None

    return datetime.utcnow() + timedelta(seconds=int(expires_in))


def get_outlook_profile(access_token: str) -> dict:
    profile = graph_get_json(
        f"{MICROSOFT_GRAPH_BASE_URL}/me?$select=mail,userPrincipalName,displayName",
        access_token,
    )
    email_address = profile.get("mail") or profile.get("userPrincipalName")
    if not email_address:
        raise RuntimeError("Could not determine Outlook email address from Microsoft Graph.")

    return {
        "emailAddress": email_address,
        "displayName": profile.get("displayName", ""),
    }


def format_outlook_message(message: dict) -> dict:
    sender = message.get("from", {}).get("emailAddress", {})

    return {
        "id": message["id"],
        "subject": message.get("subject") or "(no subject)",
        "from": sender.get("address") or sender.get("name") or "(unknown sender)",
        "snippet": message.get("bodyPreview") or "No preview text.",
        "date": message.get("receivedDateTime") or "",
        "receivedAt": message.get("receivedDateTime") or "",
    }


def parse_outlook_sender(sender_payload: dict):
    sender = sender_payload.get("emailAddress", {})
    email_address = sender.get("address")
    sender_domain = email_address.split("@", 1)[1].lower() if email_address and "@" in email_address else None
    return sender.get("name") or None, email_address or None, sender_domain


def join_recipient_values(recipients: list[dict] | None) -> str | None:
    if not recipients:
        return None

    values = []
    for recipient in recipients:
        display_name, email_address = parseaddr(
            recipient.get("emailAddress", {}).get("address") or ""
        )
        name = recipient.get("emailAddress", {}).get("name") or display_name
        if name and email_address:
            values.append(f"{name} <{email_address}>")
        elif email_address:
            values.append(email_address)
        elif name:
            values.append(name)

    return ", ".join(values) if values else None


def map_outlook_message_for_storage(message: dict) -> dict:
    sender_display, sender_email, sender_domain = parse_outlook_sender(
        message.get("from", {})
    )
    body = message.get("body", {}) or {}
    body_content_type = (body.get("contentType") or "").lower()
    body_content = body.get("content") or ""

    return {
        "platform": "outlook",
        "source_id": message["id"],
        "thread_id": message.get("conversationId"),
        "timestamp_iso": parse_graph_datetime(message.get("receivedDateTime")),
        "label_ids": message.get("categories", []),
        "sender_id": message.get("internetMessageId"),
        "sender_display": sender_display,
        "sender_email": sender_email,
        "sender_domain": sender_domain,
        "subject": message.get("subject") or "(no subject)",
        "snippet": message.get("bodyPreview") or "No preview text.",
        "body_text": body_content if body_content_type == "text" else (message.get("bodyPreview") or ""),
        "body_html_present": body_content_type == "html",
        "attachments_present": bool(message.get("hasAttachments")),
        "mime_parts": [
            {
                "contentType": body.get("contentType"),
                "size": len(body_content),
            }
        ]
        if body_content or body.get("contentType")
        else [],
        "provider_metadata": {
            "conversationIndex": message.get("conversationIndex"),
            "webLink": message.get("webLink"),
            "importance": message.get("importance"),
            "isRead": message.get("isRead"),
        },
        "from_raw": join_recipient_values([message.get("from", {})]),
        "to_raw": join_recipient_values(message.get("toRecipients")),
        "cc_raw": join_recipient_values(message.get("ccRecipients")),
        "bcc_raw": join_recipient_values(message.get("bccRecipients")),
    }


def fetch_outlook_messages(access_token: str, url: str) -> list[dict]:
    response = graph_get_json(url, access_token)
    messages = response.get("value", [])

    logger.info("Fetched %s Outlook messages", len(messages))
    if messages:
        first_message = format_outlook_message(messages[0])
        logger.info(
            "First Outlook message subject=%s receivedAt=%s from=%s",
            first_message["subject"],
            first_message["receivedAt"],
            first_message["from"],
        )
    else:
        logger.info("Outlook message fetch returned no results")

    return messages


def fetch_latest_outlook_received_at(access_token: str):
    messages = fetch_outlook_messages(
        access_token,
        build_graph_url(
            OUTLOOK_INBOX_MESSAGES_PATH,
            {
                "$top": 1,
                "$orderby": "receivedDateTime desc",
                "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,body,hasAttachments,toRecipients,ccRecipients,bccRecipients,internetMessageId,categories,conversationIndex,webLink,importance,isRead",
            },
        ),
    )
    if not messages:
        return None

    return parse_graph_datetime(messages[0].get("receivedDateTime"))


def complete_outlook_link(user_id: int, code: str) -> str:
    token_data = microsoft_token_request(
        {
            "client_id": Config.MICROSOFT_CLIENT_ID,
            "client_secret": Config.MICROSOFT_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": Config.MICROSOFT_REDIRECT_URI,
            "scope": " ".join(Config.MICROSOFT_SCOPES),
        }
    )

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    token_expiry = compute_expiry(token_data.get("expires_in"))
    profile = get_outlook_profile(access_token)
    last_received_at = fetch_latest_outlook_received_at(access_token)

    save_outlook_link(
        user_id=user_id,
        email_address=profile["emailAddress"],
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=token_expiry,
        last_received_at=last_received_at,
    )

    logger.info(
        "Completed Outlook link for user_id=%s email_address=%s refresh_token_present=%s initial_last_received_at=%s",
        user_id,
        profile["emailAddress"],
        bool(refresh_token),
        last_received_at,
    )
    return profile["emailAddress"]


def build_outlook_access_token(user_id: int, *, link: dict | None = None) -> str:
    link = _require_outlook_link(user_id, link)

    expiry = normalize_expiry(link["token_expiry"])
    is_expired = expiry and expiry <= datetime.utcnow()
    logger.info(
        "Loaded Outlook link for user_id=%s email_address=%s token_expiry=%s has_refresh_token=%s",
        user_id,
        link["email_address"],
        expiry,
        bool(link["refresh_token"]),
    )

    if is_expired and link["refresh_token"]:
        logger.info("Refreshing expired Outlook token for user_id=%s", user_id)
        token_data = microsoft_token_request(
            {
                "client_id": Config.MICROSOFT_CLIENT_ID,
                "client_secret": Config.MICROSOFT_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": link["refresh_token"],
                "redirect_uri": Config.MICROSOFT_REDIRECT_URI,
                "scope": " ".join(Config.MICROSOFT_SCOPES),
            }
        )

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        token_expiry = compute_expiry(token_data.get("expires_in"))
        save_outlook_link(
            user_id=user_id,
            email_address=link["email_address"],
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
            last_received_at=link["last_received_at"],
        )
        logger.info("Refreshed Outlook token for user_id=%s", user_id)
        return access_token

    return link["access_token"]


def list_recent_outlook_messages(user_id: int, limit: int = 5, *, link: dict | None = None) -> dict:
    link = _require_outlook_link(user_id, link)
    access_token = build_outlook_access_token(user_id, link=link)
    logger.info(
        "Loading recent Outlook inbox messages for user_id=%s limit=%s",
        user_id,
        limit,
    )
    messages = fetch_outlook_messages(
        access_token,
        build_graph_url(
            OUTLOOK_INBOX_MESSAGES_PATH,
            {
                "$top": limit,
                "$orderby": "receivedDateTime desc",
                "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,body,hasAttachments,toRecipients,ccRecipients,bccRecipients,internetMessageId,categories,conversationIndex,webLink,importance,isRead",
            },
        ),
    )
    save_messages(
        user_id,
        [map_outlook_message_for_storage(message) for message in messages],
    )
    formatted_messages = [format_outlook_message(message) for message in messages]

    latest_received_at = None
    if formatted_messages:
        latest_received_at = parse_graph_datetime(formatted_messages[0]["receivedAt"])
        update_outlook_last_received_at(user_id, latest_received_at)
        logger.info(
            "Updated Outlook last_received_at for user_id=%s to %s after recent fetch",
            user_id,
            latest_received_at,
        )
    else:
        logger.info("No recent Outlook inbox messages found for user_id=%s", user_id)

    return {
        "messages": formatted_messages,
        "lastReceivedAt": formatted_messages[0]["receivedAt"] if formatted_messages else None,
    }


def list_new_outlook_messages(user_id: int, *, link: dict | None = None) -> dict:
    link = _require_outlook_link(user_id, link)

    if not link["last_received_at"]:
        logger.info(
            "No Outlook last_received_at cursor exists for user_id=%s, returning no new messages",
            user_id,
        )
        return {"messages": [], "lastReceivedAt": None}

    access_token = build_outlook_access_token(user_id, link=link)
    last_received_at = link["last_received_at"].astimezone(timezone.utc).isoformat()
    logger.info(
        "Loading new Outlook inbox messages for user_id=%s after %s",
        user_id,
        last_received_at,
    )

    messages = fetch_outlook_messages(
        access_token,
        build_graph_url(
            OUTLOOK_INBOX_MESSAGES_PATH,
            {
                "$top": 10,
                "$orderby": "receivedDateTime desc",
                "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,body,hasAttachments,toRecipients,ccRecipients,bccRecipients,internetMessageId,categories,conversationIndex,webLink,importance,isRead",
                "$filter": f"receivedDateTime gt {last_received_at}",
            },
        ),
    )
    save_messages(
        user_id,
        [map_outlook_message_for_storage(message) for message in messages],
    )
    formatted_messages = [format_outlook_message(message) for message in messages]

    newest_received_at = None
    if formatted_messages:
        newest_received_at = parse_graph_datetime(formatted_messages[0]["receivedAt"])
        update_outlook_last_received_at(user_id, newest_received_at)
        logger.info(
            "Updated Outlook last_received_at for user_id=%s to %s after new-message fetch",
            user_id,
            newest_received_at,
        )
    else:
        logger.info("No new Outlook inbox messages found for user_id=%s", user_id)

    return {
        "messages": formatted_messages,
        "lastReceivedAt": formatted_messages[0]["receivedAt"] if formatted_messages else None,
    }
