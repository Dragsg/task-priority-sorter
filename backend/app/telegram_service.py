from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from secrets import choice
from urllib import error, parse, request

from config import Config
from .db import (
    claim_telegram_alert,
    claim_telegram_digest,
    clear_telegram_alert_claim,
    clear_telegram_digest_claim,
    consume_telegram_link_code,
    create_telegram_link_code,
    delete_telegram_link,
    get_active_telegram_link_code,
    get_telegram_link,
    get_telegram_notification_settings,
    get_user_by_id,
    list_telegram_link_user_ids,
    mark_telegram_alert_sent,
    mark_telegram_digest_sent,
    save_telegram_notification_settings,
)
from .time_utils import now_sgt, parse_iso_to_sgt

logger = logging.getLogger(__name__)

LINK_CODE_PREFIX = "TPS"
LINK_CODE_LENGTH = 8
LINK_CODE_TTL_MINUTES = 15
DEFAULT_DIGEST_TIME = "08:00"
SUPPORTED_PRIORITY_TIERS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def get_default_telegram_settings() -> dict:
    return {
        "telegramEnabled": True,
        "instantCritical": True,
        "instantHigh": True,
        "instantMedium": False,
        "instantLow": False,
        "dailyDigestEnabled": True,
        "dailyDigestTime": DEFAULT_DIGEST_TIME,
    }


def get_telegram_configuration_error(*, require_bot_username: bool = False) -> str | None:
    missing: list[str] = []
    if not Config.TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if require_bot_username and not Config.TELEGRAM_BOT_USERNAME:
        missing.append("TELEGRAM_BOT_USERNAME")
    if missing:
        return "Telegram is not configured. Missing: " + ", ".join(missing)
    return None


def _require_telegram_configuration(*, require_bot_username: bool = False) -> None:
    configuration_error = get_telegram_configuration_error(
        require_bot_username=require_bot_username
    )
    if configuration_error:
        raise RuntimeError(configuration_error)


def _normalize_settings_row(row: dict | None) -> dict:
    defaults = get_default_telegram_settings()
    if not row:
        return defaults

    return {
        "telegramEnabled": bool(row.get("telegram_enabled", defaults["telegramEnabled"])),
        "instantCritical": bool(row.get("alert_critical", defaults["instantCritical"])),
        "instantHigh": bool(row.get("alert_high", defaults["instantHigh"])),
        "instantMedium": bool(row.get("alert_medium", defaults["instantMedium"])),
        "instantLow": bool(row.get("alert_low", defaults["instantLow"])),
        "dailyDigestEnabled": bool(
            row.get("daily_digest_enabled", defaults["dailyDigestEnabled"])
        ),
        "dailyDigestTime": str(row.get("daily_digest_time") or defaults["dailyDigestTime"]),
    }


def _serialize_link(link: dict | None) -> dict | None:
    if not link:
        return None

    return {
        "chatId": str(link["telegram_chat_id"]),
        "chatType": link.get("telegram_chat_type"),
        "username": link.get("telegram_username"),
        "displayName": link.get("telegram_display_name"),
        "linkedAt": link["linked_at"].isoformat() if link.get("linked_at") else None,
    }


def _serialize_pending_link(code_row: dict | None) -> dict | None:
    if not code_row:
        return None

    bot_username = (Config.TELEGRAM_BOT_USERNAME or "").lstrip("@")
    deep_link = None
    if bot_username:
        deep_link = f"https://t.me/{bot_username}?start={parse.quote(str(code_row['code']))}"

    return {
        "code": code_row["code"],
        "expiresAt": code_row["expires_at"].isoformat() if code_row.get("expires_at") else None,
        "botUsername": bot_username or None,
        "botDeepLink": deep_link,
    }


def get_telegram_settings_payload(user_id: int) -> dict:
    configuration_error = get_telegram_configuration_error(require_bot_username=True)
    settings_row = get_telegram_notification_settings(user_id)
    link = get_telegram_link(user_id)
    pending_code = get_active_telegram_link_code(user_id)

    return {
        "configured": configuration_error is None,
        "configurationError": configuration_error,
        "botUsername": (Config.TELEGRAM_BOT_USERNAME or "").lstrip("@") or None,
        "linked": bool(link),
        "linkedChat": _serialize_link(link),
        "pendingLink": _serialize_pending_link(pending_code),
        "settings": _normalize_settings_row(settings_row),
    }


def validate_digest_time(value: str) -> str:
    cleaned = (value or "").strip()
    try:
        return datetime.strptime(cleaned, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError("dailyDigestTime must use 24-hour HH:MM format.") from exc


def update_telegram_settings(user_id: int, payload: dict | None) -> dict:
    data = payload or {}
    if not isinstance(data, dict):
        raise ValueError("Telegram settings must be a JSON object.")

    defaults = get_default_telegram_settings()
    normalized: dict[str, bool | str] = {}
    field_map = {
        "telegramEnabled": "telegramEnabled",
        "instantCritical": "instantCritical",
        "instantHigh": "instantHigh",
        "instantMedium": "instantMedium",
        "instantLow": "instantLow",
        "dailyDigestEnabled": "dailyDigestEnabled",
    }
    for incoming_field, output_field in field_map.items():
        value = data.get(incoming_field, defaults[output_field])
        if not isinstance(value, bool):
            raise ValueError(f"{incoming_field} must be true or false.")
        normalized[output_field] = value

    digest_time = validate_digest_time(
        str(data.get("dailyDigestTime", defaults["dailyDigestTime"]))
    )
    normalized["dailyDigestTime"] = digest_time

    save_telegram_notification_settings(
        user_id,
        telegram_enabled=bool(normalized["telegramEnabled"]),
        alert_critical=bool(normalized["instantCritical"]),
        alert_high=bool(normalized["instantHigh"]),
        alert_medium=bool(normalized["instantMedium"]),
        alert_low=bool(normalized["instantLow"]),
        daily_digest_enabled=bool(normalized["dailyDigestEnabled"]),
        daily_digest_time=digest_time,
    )

    return get_telegram_settings_payload(user_id)


def _generate_linking_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"{LINK_CODE_PREFIX}-" + "".join(choice(alphabet) for _ in range(LINK_CODE_LENGTH))


def generate_telegram_link_code(user_id: int) -> dict:
    _require_telegram_configuration(require_bot_username=True)
    code = _generate_linking_code()
    expires_at = now_sgt() + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    create_telegram_link_code(user_id, code=code, expires_at=expires_at)
    return get_telegram_settings_payload(user_id)


def disconnect_telegram(user_id: int) -> dict:
    delete_telegram_link(user_id)
    return get_telegram_settings_payload(user_id)


def _telegram_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/{method}"


def _send_telegram_api_request(method: str, payload: dict) -> dict:
    _require_telegram_configuration(require_bot_username=False)
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        _telegram_api_url(method),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Telegram API request failed with status {exc.code}: {details}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Telegram API request failed: {exc.reason}") from exc


def _send_message(chat_id: str, text: str) -> dict:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    response = _send_telegram_api_request("sendMessage", payload)
    if not response.get("ok"):
        raise RuntimeError(
            f"Telegram API rejected the message: {response.get('description', 'unknown error')}"
        )
    return response.get("result") or {}


def _truncate_text(value: str | None, limit: int = 180) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _format_deadline(deadline_iso: str | None) -> str | None:
    parsed = parse_iso_to_sgt(deadline_iso)
    if parsed is None:
        return None
    return parsed.strftime("%a %d %b, %I:%M %p")


def _app_task_link() -> str | None:
    frontend_url = (Config.FRONTEND_URL or "").strip()
    if not frontend_url:
        return None
    return frontend_url.rstrip("/") + "/kanban"


def _format_source_label(task: dict) -> str | None:
    platforms = task.get("platforms_seen")
    if isinstance(platforms, list) and platforms:
        platform = str(platforms[0]).lower()
    else:
        platform = None

    sender = _truncate_text(task.get("source_sender"), limit=60)
    if platform and sender:
        return f"{platform} from {sender}"
    if platform:
        return platform
    if sender:
        return sender
    return None


def _build_instant_alert_message(task: dict) -> str:
    lines = ["New task alert", ""]
    title = _truncate_text(task.get("task_title") or task.get("entity_name") or "Untitled task", limit=120)
    lines.append(f"Task: {title}")
    lines.append(f"Priority: {str(task.get('priority_tier') or 'LOW').upper()}")

    deadline = _format_deadline(task.get("deadline_at_iso"))
    if deadline:
        lines.append(f"Deadline: {deadline}")

    summary = _truncate_text(task.get("task_description") or task.get("rationale"), limit=220)
    if summary:
        lines.append(f"Why now: {summary}")

    source = _format_source_label(task)
    if source:
        lines.append(f"Source: {source}")

    app_link = _app_task_link()
    if app_link:
        lines.append(f"Open app: {app_link}")

    return "\n".join(lines)


def _priority_pref_enabled(settings: dict, priority_tier: str | None) -> bool:
    priority = str(priority_tier or "").upper()
    if priority == "CRITICAL":
        return bool(settings["instantCritical"])
    if priority == "HIGH":
        return bool(settings["instantHigh"])
    if priority == "MEDIUM":
        return bool(settings["instantMedium"])
    if priority == "LOW":
        return bool(settings["instantLow"])
    return False


def send_instant_telegram_alerts(user_id: int, task_payloads: list[dict]) -> dict:
    summary = {"sent": 0, "skipped": 0, "errors": 0}

    if not task_payloads:
        return summary

    configuration_error = get_telegram_configuration_error(require_bot_username=False)
    if configuration_error:
        logger.info("Skipping Telegram instant alerts for user_id=%s: %s", user_id, configuration_error)
        summary["skipped"] += len(task_payloads)
        return summary

    settings = _normalize_settings_row(get_telegram_notification_settings(user_id))
    link = get_telegram_link(user_id)
    if not link or not settings["telegramEnabled"]:
        summary["skipped"] += len(task_payloads)
        return summary

    chat_id = str(link["telegram_chat_id"])

    for task in task_payloads:
        priority_tier = str(task.get("priority_tier") or "").upper()
        status = str(task.get("status") or "").lower()
        canonical_task_id = str(task.get("canonical_task_id") or "")

        if status == "completed" or not canonical_task_id:
            summary["skipped"] += 1
            continue
        if not _priority_pref_enabled(settings, priority_tier):
            summary["skipped"] += 1
            continue
        if not claim_telegram_alert(
            user_id,
            canonical_task_id=canonical_task_id,
            priority_tier=priority_tier,
            task_payload=task,
        ):
            summary["skipped"] += 1
            continue

        try:
            result = _send_message(chat_id, _build_instant_alert_message(task))
            mark_telegram_alert_sent(
                user_id,
                canonical_task_id=canonical_task_id,
                message_id=str(result.get("message_id") or ""),
            )
            summary["sent"] += 1
        except Exception:
            clear_telegram_alert_claim(user_id, canonical_task_id=canonical_task_id)
            summary["errors"] += 1
            logger.exception(
                "Telegram instant alert failed for user_id=%s canonical_task_id=%s",
                user_id,
                canonical_task_id,
            )

    return summary


def _digest_due_today(task: dict, now: datetime) -> bool:
    deadline = parse_iso_to_sgt(task.get("deadline_at_iso"))
    if deadline is None:
        return False
    return deadline.date() <= now.date()


def _digest_sort_key(task: dict, now: datetime) -> tuple[int, float, int, str]:
    deadline = parse_iso_to_sgt(task.get("deadline_at_iso"))
    is_due = deadline is not None and deadline.date() <= now.date()
    is_overdue = deadline is not None and deadline < now
    priority = str(task.get("priority_tier") or "LOW").upper()
    priority_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(priority, 4)
    deadline_rank = task.get("deadline_hours")
    if not isinstance(deadline_rank, (int, float)):
        deadline_rank = 10**6
    title = str(task.get("task_title") or task.get("entity_name") or "")
    return (0 if is_overdue else 1 if is_due else 2, float(deadline_rank), priority_rank, title.lower())


def _build_digest_message(open_tasks: list[dict], now: datetime) -> str:
    important_tasks = [
        task
        for task in open_tasks
        if str(task.get("priority_tier") or "").upper() in {"CRITICAL", "HIGH"}
        or _digest_due_today(task, now)
    ]
    important_tasks.sort(key=lambda task: _digest_sort_key(task, now))

    header = f"Daily digest for {now.strftime('%a %d %b')}"
    lines = [header, ""]

    if not important_tasks:
        lines.append("Nothing urgent today. Keep your pace steady and check in when you're ready.")
        lines.append(f"Open tasks remaining: {len(open_tasks)}")
        return "\n".join(lines)

    lines.append("Suggested order of action:")
    for index, task in enumerate(important_tasks[:5], start=1):
        title = _truncate_text(task.get("task_title") or task.get("entity_name") or "Untitled task", limit=90)
        priority = str(task.get("priority_tier") or "LOW").upper()
        deadline = _format_deadline(task.get("deadline_at_iso"))
        suffix = f" — due {deadline}" if deadline else ""
        lines.append(f"{index}. [{priority}] {title}{suffix}")

    lines.append("")
    critical_high_count = sum(
        1
        for task in open_tasks
        if str(task.get("priority_tier") or "").upper() in {"CRITICAL", "HIGH"}
    )
    due_today_or_overdue = sum(1 for task in open_tasks if _digest_due_today(task, now))
    lines.append(f"Critical/high tasks: {critical_high_count}")
    lines.append(f"Due today or overdue: {due_today_or_overdue}")
    lines.append(f"Open tasks remaining: {len(open_tasks)}")

    app_link = _app_task_link()
    if app_link:
        lines.append(f"Open app: {app_link}")

    return "\n".join(lines)


def send_daily_telegram_digest(user_id: int, *, now: datetime | None = None) -> bool:
    configuration_error = get_telegram_configuration_error(require_bot_username=False)
    if configuration_error:
        logger.info("Skipping Telegram digest for user_id=%s: %s", user_id, configuration_error)
        return False

    settings = _normalize_settings_row(get_telegram_notification_settings(user_id))
    link = get_telegram_link(user_id)
    if not link or not settings["telegramEnabled"] or not settings["dailyDigestEnabled"]:
        return False

    current_time = now or now_sgt()
    digest_time = validate_digest_time(str(settings["dailyDigestTime"]))
    if current_time.strftime("%H:%M") < digest_time:
        return False

    digest_date = current_time.date()
    if not claim_telegram_digest(user_id, digest_date=digest_date):
        return False

    try:
        from .pipeline_bridge import list_prioritized_tasks

        open_tasks = [
            task
            for task in list_prioritized_tasks(user_id)
            if str(task.get("status") or "").lower() != "completed"
        ]
        message = _build_digest_message(open_tasks, current_time)
        result = _send_message(str(link["telegram_chat_id"]), message)
        mark_telegram_digest_sent(
            user_id,
            digest_date=digest_date,
            message_id=str(result.get("message_id") or ""),
            summary={"openTaskCount": len(open_tasks)},
        )
        return True
    except Exception:
        clear_telegram_digest_claim(user_id, digest_date=digest_date)
        logger.exception("Telegram daily digest failed for user_id=%s", user_id)
        return False


def send_due_telegram_digests(*, now: datetime | None = None) -> dict:
    summary = {"checked": 0, "sent": 0}
    for user_id in list_telegram_link_user_ids():
        summary["checked"] += 1
        if send_daily_telegram_digest(user_id, now=now):
            summary["sent"] += 1
    return summary


def send_telegram_test_message(user_id: int) -> dict:
    configuration_error = get_telegram_configuration_error(require_bot_username=False)
    if configuration_error:
        raise RuntimeError(configuration_error)

    link = get_telegram_link(user_id)
    if not link:
        raise RuntimeError("Link Telegram before sending a test message.")

    result = _send_message(
        str(link["telegram_chat_id"]),
        "Telegram notifications are working. New task alerts and your daily digest will arrive here.",
    )
    return {
        "success": True,
        "messageId": str(result.get("message_id") or ""),
    }


def _extract_code_from_message(text: str | None) -> str | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("/start"):
        parts = cleaned.split(maxsplit=1)
        if len(parts) == 2:
            return parts[1].strip().upper()
        return None
    return cleaned.upper()


def process_telegram_webhook(payload: dict | None, *, secret_header: str | None = None) -> dict:
    configured_error = get_telegram_configuration_error(require_bot_username=False)
    if configured_error:
        raise RuntimeError(configured_error)

    expected_secret = (Config.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if expected_secret and secret_header != expected_secret:
        raise PermissionError("Invalid Telegram webhook secret.")

    if not isinstance(payload, dict):
        raise ValueError("Telegram webhook payload must be a JSON object.")
    if not isinstance(payload.get("update_id"), int):
        raise ValueError("Telegram webhook payload is missing update_id.")

    message = payload.get("message")
    if not isinstance(message, dict):
        return {"processed": False, "reason": "unsupported_update"}

    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("id") is None:
        raise ValueError("Telegram webhook payload is missing chat information.")

    text = message.get("text")
    code = _extract_code_from_message(text)
    chat_id = str(chat["id"])
    chat_type = str(chat.get("type") or "")
    sender = message.get("from")
    sender_data = sender if isinstance(sender, dict) else {}
    chat_username = sender_data.get("username")
    first_name = sender_data.get("first_name") or chat.get("title") or "there"

    if not code:
        _send_message(
            chat_id,
            "Send the linking code from your account settings here to connect this Telegram chat.",
        )
        return {"processed": True, "reason": "missing_code"}

    try:
        link_result = consume_telegram_link_code(
            code,
            chat_id=chat_id,
            chat_type=chat_type,
            chat_username=chat_username,
            chat_display_name=str(first_name),
            now=now_sgt(),
        )
        user = get_user_by_id(int(link_result["user_id"]))
        username = user["username"] if user else "your account"
        _send_message(
            chat_id,
            f"Telegram is now linked to {username}. You can return to the app and start using alerts.",
        )
        return {"processed": True, "linked": True, "userId": int(link_result["user_id"])}
    except Exception as exc:
        _send_message(chat_id, f"Could not link this chat: {exc}")
        return {"processed": True, "linked": False, "error": str(exc)}
