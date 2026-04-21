import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config
from .db import (
    get_outlook_link,
    save_outlook_link,
    update_outlook_last_received_at,
)

logger = logging.getLogger(__name__)

MICROSOFT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def normalize_expiry(expiry):
    if not expiry:
        return None

    if expiry.tzinfo is None:
        return expiry

    return expiry.astimezone(timezone.utc).replace(tzinfo=None)


def parse_graph_datetime(value: str | None):
    if not value:
        return None

    return normalize_expiry(datetime.fromisoformat(value.replace("Z", "+00:00")))


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
            return json.loads(response.read().decode("utf-8"))
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


def fetch_outlook_messages(access_token: str, url: str) -> list[dict]:
    response = graph_get_json(url, access_token)
    return [format_outlook_message(item) for item in response.get("value", [])]


def fetch_latest_outlook_received_at(access_token: str):
    messages = fetch_outlook_messages(
        access_token,
        build_graph_url(
            "/me/messages",
            {
                "$top": 1,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
            },
        ),
    )
    if not messages:
        return None

    return parse_graph_datetime(messages[0]["receivedAt"])


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
        "Completed Outlook link for user_id=%s email_address=%s",
        user_id,
        profile["emailAddress"],
    )
    return profile["emailAddress"]


def build_outlook_access_token(user_id: int) -> str:
    link = get_outlook_link(user_id)

    if not link:
        logger.info("No saved Outlook link available for user_id=%s", user_id)
        raise RuntimeError("No Outlook account is linked for this user yet.")

    expiry = normalize_expiry(link["token_expiry"])
    is_expired = expiry and expiry <= datetime.utcnow()

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


def list_recent_outlook_messages(user_id: int, limit: int = 5) -> dict:
    access_token = build_outlook_access_token(user_id)
    messages = fetch_outlook_messages(
        access_token,
        build_graph_url(
            "/me/messages",
            {
                "$top": limit,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
            },
        ),
    )

    latest_received_at = None
    if messages:
        latest_received_at = parse_graph_datetime(messages[0]["receivedAt"])
        update_outlook_last_received_at(user_id, latest_received_at)

    return {
        "messages": messages,
        "lastReceivedAt": messages[0]["receivedAt"] if messages else None,
    }


def list_new_outlook_messages(user_id: int) -> dict:
    link = get_outlook_link(user_id)
    if not link:
        raise RuntimeError("No Outlook account is linked for this user yet.")

    if not link["last_received_at"]:
        return {"messages": [], "lastReceivedAt": None}

    access_token = build_outlook_access_token(user_id)
    last_received_at = link["last_received_at"].astimezone(timezone.utc).isoformat()

    messages = fetch_outlook_messages(
        access_token,
        build_graph_url(
            "/me/messages",
            {
                "$top": 10,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
                "$filter": f"receivedDateTime gt {last_received_at}",
            },
        ),
    )

    newest_received_at = None
    if messages:
        newest_received_at = parse_graph_datetime(messages[0]["receivedAt"])
        update_outlook_last_received_at(user_id, newest_received_at)

    return {
        "messages": messages,
        "lastReceivedAt": messages[0]["receivedAt"] if messages else None,
    }
