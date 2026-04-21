from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Config
from .db import get_gmail_link, save_gmail_link, update_gmail_history

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


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
        credentials.refresh(Request())
        save_gmail_link(
            user_id=user_id,
            email_address=link["email_address"],
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            token_expiry=normalize_expiry(credentials.expiry),
            history_id=link["history_id"],
        )

    return credentials


def build_gmail_client(user_id: int):
    credentials = build_credentials(user_id)
    return build("gmail", "v1", credentials=credentials)


def format_message(message: dict) -> dict:
    headers = {
        header["name"].lower(): header["value"]
        for header in message.get("payload", {}).get("headers", [])
    }

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


def get_message_detail(service, message_id: str) -> dict:
    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="metadata")
        .execute()
    )
    return format_message(message)


def list_recent_messages(user_id: int, limit: int = 5) -> dict:
    service = build_gmail_client(user_id)
    response = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], maxResults=limit)
        .execute()
    )

    messages = [
        get_message_detail(service, item["id"])
        for item in response.get("messages", [])
    ]

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

    messages = [get_message_detail(service, message_id) for message_id in message_ids]
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

    return profile["emailAddress"]
