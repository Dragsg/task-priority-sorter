import logging
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from threading import Thread
from urllib.parse import urlencode

import bcrypt
import jwt
from flask import Blueprint, current_app, jsonify, redirect, request, session

from config import Config
from .background_sync import get_background_sync_status
from .db import (
    create_user,
    delete_user_account,
    get_gmail_link,
    get_outlook_link,
    get_user_by_username,
    get_user_by_id,
    update_user_onboarding_answers,
    update_user_username,
)
from .pipeline_bridge import (
    clear_user_runtime_state,
    create_manual_task,
    get_available_tags,
    list_false_negative_items,
    get_onboarding_context_snapshot,
    get_pipeline_recompute_status,
    get_profile_snapshot,
    get_task_statistics_snapshot,
    list_prioritized_tasks,
    promote_false_negative_email,
    remove_prioritized_task,
    remove_calendar_context,
    run_prioritization_for_user,
    save_calendar_context,
    submit_task_feedback,
    sync_onboarding_context,
    update_prioritized_task,
    update_prioritized_task_tags,
)
from .account_utils import (
    normalize_username,
    normalize_important_topic,
    normalize_performance_time,
    normalize_prioritise_by,
    serialize_user,
    validate_username,
    validate_important_topic,
    validate_password,
    validate_performance_time,
    validate_prioritise_by,
)
from .gmail_service import (
    build_google_flow,
    complete_gmail_link,
    list_new_messages,
    list_recent_messages,
)
from .outlook_service import (
    build_microsoft_authorize_url,
    complete_outlook_link,
    list_new_outlook_messages,
    list_recent_outlook_messages,
)
from .telegram_service import (
    disconnect_telegram,
    generate_telegram_link_code,
    get_telegram_settings_payload,
    process_telegram_webhook,
    send_telegram_test_message,
    update_telegram_settings,
)

api = Blueprint("api", __name__)
ALLOWED_RECENT_LIMITS = {5, 10, 20, 50, 100}
logger = logging.getLogger(__name__)


def build_frontend_redirect_url(*, path: str = "", query_params: dict[str, str] | None = None) -> str:
    base_url = current_app.config["FRONTEND_URL"].rstrip("/")
    normalized_path = f"/{path.lstrip('/')}" if path else ""
    query = urlencode(query_params or {})
    return f"{base_url}{normalized_path}?{query}" if query else f"{base_url}{normalized_path}"


def build_token(user_id: int) -> str:
    return jwt.encode(
        {
            "user_id": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        Config.SECRET_KEY,
        algorithm="HS256",
    )


def get_authenticated_user_id(required: bool = False):
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
            return int(payload["user_id"])
        except jwt.ExpiredSignatureError as error:
            raise RuntimeError("Token expired") from error
        except jwt.InvalidTokenError as error:
            raise RuntimeError("Invalid token") from error

    user_id = request.args.get("user_id", type=int)
    if user_id is not None:
        return user_id

    raise RuntimeError("Unauthorised")


def get_status_code(error: Exception) -> int:
    if str(error) in {"Unauthorised", "Token expired", "Invalid token"}:
        return 401
    if str(error).startswith("Telegram is not configured"):
        return 503
    if isinstance(error, PermissionError):
        return 401
    return 400


def get_recent_limit() -> int:
    limit = request.args.get("limit", default=5, type=int)
    if limit not in ALLOWED_RECENT_LIMITS:
        raise RuntimeError("Limit must be one of 5, 10, 20, 50, or 100")
    return limit


def _run_user_account_deletion(user_id: int) -> None:
    try:
        delete_user_account(user_id)
        clear_user_runtime_state(user_id)
    except Exception:  # pragma: no cover - background failure path
        logger.exception("Background account deletion failed for user_id=%s", user_id)


def _start_user_account_deletion(user_id: int) -> None:
    Thread(
        target=_run_user_account_deletion,
        args=(user_id,),
        name=f"delete-user-{user_id}",
        daemon=True,
    ).start()


@api.post("/signup")
def signup():
    try:
        data = request.get_json() or {}
        username = normalize_username(data.get("username"))
        password = data.get("password") or ""

        validate_username(username)
        validate_password(password)

        existing_user = get_user_by_username(username)
        if existing_user:
            return jsonify({"success": False, "error": "Username already exists"}), 409

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
        user = create_user(username=username, password_hash=password_hash)
        token = build_token(user["user_id"])
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 422
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "success": True,
            "token": token,
            "user": serialize_user(user),
        }
    )


@api.post("/login")
def login():
    try:
        data = request.get_json() or {}
        username = normalize_username(data.get("username"))
        password = data.get("password") or ""

        validate_username(username)
        if not password:
            raise ValueError("Password is required.")

        user = get_user_by_username(username)
        if not user:
            return jsonify({"success": False, "error": "Invalid username or password"}), 401

        is_valid_password = bcrypt.checkpw(
            password.encode("utf-8"),
            user["password"].encode("utf-8"),
        )
        if not is_valid_password:
            return jsonify({"success": False, "error": "Invalid username or password"}), 401

        token = build_token(user["user_id"])
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 422
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "success": True,
            "token": token,
            "user": serialize_user(user),
        }
    )


@api.get("/user")
def current_user():
    try:
        user_id = get_authenticated_user_id(required=True)
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(serialize_user(user))


@api.patch("/user")
def update_user():
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        username = normalize_username(data.get("username"))

        validate_username(username)

        existing_user = get_user_by_username(username)
        if existing_user and existing_user["user_id"] != user_id:
            return jsonify({"error": "Username already exists"}), 409

        user = update_user_username(user_id, username)
        if not user:
            return jsonify({"error": "User not found"}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "success": True,
            "user": serialize_user(user),
        }
    )


@api.delete("/user")
def delete_user():
    try:
        user_id = get_authenticated_user_id(required=True)
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        data = request.get_json() or {}
        confirmation_username = normalize_username(data.get("username"))
        if confirmation_username != user["username"]:
            raise ValueError("Type your current username exactly to confirm account deletion.")

        _start_user_account_deletion(user_id)
        session.clear()
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify({"success": True}), 202


@api.put("/onboarding")
def onboarding():
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        performance_time = normalize_performance_time(data.get("performanceTime"))
        important_topic = normalize_important_topic(data.get("importantTopic"))
        prioritise_by = normalize_prioritise_by(data.get("prioritiseBy"))

        validate_performance_time(performance_time)
        validate_important_topic(important_topic)
        validate_prioritise_by(prioritise_by)

        user = update_user_onboarding_answers(
            user_id,
            performance_time=performance_time,
            important_topic=important_topic,
            prioritise_by=prioritise_by,
        )
        if not user:
            return jsonify({"error": "User not found"}), 404
        sync_onboarding_context(user_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "success": True,
            "user": serialize_user(user),
        }
    )


@api.get("/onboarding/context")
def onboarding_context():
    try:
        user_id = get_authenticated_user_id(required=True)
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        context = get_onboarding_context_snapshot(user_id, user=user)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "user": serialize_user(user),
            "onboarding": context,
            "calendarActive": bool(context.get("calendar_source")),
        }
    )


@api.post("/onboarding/calendar")
def onboarding_calendar_upload():
    try:
        user_id = get_authenticated_user_id(required=True)
        uploaded = request.files.get("file")
        if uploaded is None:
            raise ValueError("Calendar file is required.")
        if not uploaded.filename:
            raise ValueError("Calendar file must include a filename.")
        context = save_calendar_context(
            user_id,
            filename=uploaded.filename,
            file_bytes=uploaded.read(),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify({"success": True, "onboarding": context, "calendarActive": bool(context.get("calendar_source"))})


@api.delete("/onboarding/calendar")
def onboarding_calendar_delete():
    try:
        user_id = get_authenticated_user_id(required=True)
        context = remove_calendar_context(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify({"success": True, "onboarding": context, "calendarActive": False})


@api.get("/gmail/status")
def gmail_status():
    try:
        user_id = get_authenticated_user_id()
        link = get_gmail_link(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    if not link:
        current_app.logger.info("No Gmail link exists for user_id=%s", user_id)
        return jsonify({"linked": False, "userId": user_id})

    current_app.logger.info(
        "Returning linked Gmail status for user_id=%s email_address=%s",
        user_id,
        link["email_address"],
    )
    return jsonify(
        {
            "linked": True,
            "userId": user_id,
            "emailAddress": link["email_address"],
            "linkedAt": link["linked_at"].isoformat() if link["linked_at"] else None,
            "historyId": link["history_id"],
        }
    )


@api.get("/gmail/link")
def gmail_link():
    try:
        user_id = get_authenticated_user_id()
        flow = build_google_flow()
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account consent",
        )
        session["gmail_oauth_state"] = state
        session["gmail_code_verifier"] = flow.code_verifier
        session["gmail_oauth_user_id"] = user_id
        return redirect(authorization_url)
    except Exception as error:
        return redirect(
            build_frontend_redirect_url(
                path="/linking",
                query_params={"gmail": "error", "reason": str(error)},
            )
        )


@api.get("/gmail/callback")
def gmail_callback():
    if request.args.get("error"):
        return redirect(
            build_frontend_redirect_url(
                path="/linking",
                query_params={"gmail": "error", "reason": request.args["error"]},
            )
        )

    saved_state = session.get("gmail_oauth_state")
    saved_code_verifier = session.get("gmail_code_verifier")
    incoming_state = request.args.get("state")
    if not saved_state or saved_state != incoming_state:
        return redirect(
            build_frontend_redirect_url(
                path="/linking",
                query_params={"gmail": "error", "reason": "state_mismatch"},
            )
        )

    try:
        user_id = session.get("gmail_oauth_user_id")
        if user_id is None:
            raise RuntimeError("Unauthorised")
        flow = build_google_flow()
        flow.code_verifier = saved_code_verifier
        flow.fetch_token(authorization_response=request.url)
        email_address = complete_gmail_link(user_id, flow)
        session.pop("gmail_oauth_state", None)
        session.pop("gmail_code_verifier", None)
        session.pop("gmail_oauth_user_id", None)
    except Exception as error:
        return redirect(
            build_frontend_redirect_url(
                path="/linking",
                query_params={"gmail": "error", "reason": str(error)},
            )
        )

    return redirect(
        build_frontend_redirect_url(
            path="/linking",
            query_params={"gmail": "linked", "email": email_address},
        )
    )


@api.get("/gmail/messages/recent")
def gmail_recent_messages():
    try:
        user_id = get_authenticated_user_id()
        result = list_recent_messages(user_id, limit=get_recent_limit())
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.get("/gmail/messages/new")
def gmail_new_messages():
    try:
        user_id = get_authenticated_user_id()
        result = list_new_messages(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.get("/outlook/status")
def outlook_status():
    try:
        user_id = get_authenticated_user_id()
        link = get_outlook_link(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    if not link:
        current_app.logger.info("No Outlook link exists for user_id=%s", user_id)
        return jsonify({"linked": False, "userId": user_id})

    current_app.logger.info(
        "Returning linked Outlook status for user_id=%s email_address=%s",
        user_id,
        link["email_address"],
    )
    return jsonify(
        {
            "linked": True,
            "userId": user_id,
            "emailAddress": link["email_address"],
            "linkedAt": link["linked_at"].isoformat() if link["linked_at"] else None,
            "lastReceivedAt": (
                link["last_received_at"].isoformat()
                if link["last_received_at"]
                else None
            ),
        }
    )


@api.get("/outlook/link")
def outlook_link():
    try:
        user_id = get_authenticated_user_id()
        state = token_urlsafe(24)
        session["outlook_oauth_state"] = state
        session["outlook_oauth_user_id"] = user_id
        authorization_url = build_microsoft_authorize_url(state)
        return redirect(authorization_url)
    except Exception as error:
        query = urlencode({"outlook": "error", "reason": str(error)})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")


@api.get("/outlook/callback")
def outlook_callback():
    if request.args.get("error"):
        query = urlencode(
            {
                "outlook": "error",
                "reason": request.args.get("error_description", request.args["error"]),
            }
        )
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")

    saved_state = session.get("outlook_oauth_state")
    incoming_state = request.args.get("state")
    if not saved_state or saved_state != incoming_state:
        query = urlencode({"outlook": "error", "reason": "state_mismatch"})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")

    try:
        user_id = session.get("outlook_oauth_user_id")
        if user_id is None:
            raise RuntimeError("Unauthorised")
        code = request.args.get("code")
        if not code:
            raise RuntimeError("Microsoft did not return an authorization code.")

        email_address = complete_outlook_link(user_id, code)
        session.pop("outlook_oauth_state", None)
        session.pop("outlook_oauth_user_id", None)
    except Exception as error:
        query = urlencode({"outlook": "error", "reason": str(error)})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")

    query = urlencode({"outlook": "linked", "email": email_address})
    return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")


@api.get("/outlook/messages/recent")
def outlook_recent_messages():
    try:
        user_id = get_authenticated_user_id()
        result = list_recent_outlook_messages(user_id, limit=get_recent_limit())
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.get("/outlook/messages/new")
def outlook_new_messages():
    try:
        user_id = get_authenticated_user_id()
        result = list_new_outlook_messages(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.get("/background-sync/status")
def background_sync_status():
    return jsonify(get_background_sync_status())


@api.get("/telegram/settings")
def telegram_settings():
    try:
        user_id = get_authenticated_user_id(required=True)
        payload = get_telegram_settings_payload(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(payload)


@api.put("/telegram/settings")
def telegram_settings_update():
    try:
        user_id = get_authenticated_user_id(required=True)
        payload = update_telegram_settings(user_id, request.get_json())
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(payload)


@api.post("/telegram/link-code")
def telegram_link_code():
    try:
        user_id = get_authenticated_user_id(required=True)
        payload = generate_telegram_link_code(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(payload)


@api.delete("/telegram/link")
def telegram_disconnect():
    try:
        user_id = get_authenticated_user_id(required=True)
        payload = disconnect_telegram(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(payload)


@api.post("/telegram/test")
def telegram_test():
    try:
        user_id = get_authenticated_user_id(required=True)
        result = send_telegram_test_message(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.post("/telegram/webhook")
def telegram_webhook():
    try:
        payload = process_telegram_webhook(
            request.get_json(silent=True),
            secret_header=request.headers.get("X-Telegram-Bot-Api-Secret-Token"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(payload)


@api.post("/tasks/sync")
def sync_prioritized_tasks():
    try:
        user_id = get_authenticated_user_id(required=True)
        limit = request.args.get("limit", default=None, type=int)
        logger.info(
            "Manual task priority refresh started for user_id=%s limit=%s",
            user_id,
            limit,
        )
        result = run_prioritization_for_user(user_id, limit=limit)
        logger.info(
            "Manual task priority refresh completed for user_id=%s run_id=%s raw_messages=%s task_cards=%s",
            user_id,
            result.get("runId"),
            result.get("rawMessageCount"),
            result.get("taskCardCount"),
        )
    except Exception as error:
        logger.exception("Manual task priority refresh failed")
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.post("/tasks/manual")
def add_manual_task():
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        result = create_manual_task(
            user_id,
            title=data.get("title") or "",
            description=data.get("description"),
            task_type=data.get("taskType"),
            deadline_at=data.get("deadlineAt"),
            entity_name=data.get("entityName"),
            tags=data.get("tags"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.get("/tasks")
def prioritized_tasks():
    try:
        user_id = get_authenticated_user_id(required=True)
        items = list_prioritized_tasks(user_id)
        false_negative_items = list_false_negative_items(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify({"items": items, "falseNegativeItems": false_negative_items})


@api.post("/false-negatives/queue")
def queue_false_negative_email():
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        source_id = data.get("sourceId")
        platform = data.get("platform")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("sourceId is required.")
        if platform is not None and not isinstance(platform, str):
            raise ValueError("platform must be a string.")
        result = promote_false_negative_email(
            user_id,
            source_id=source_id,
            platform=platform,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.get("/dashboard")
def dashboard_bootstrap():
    try:
        user_id = get_authenticated_user_id(required=True)
        user = get_user_by_id(user_id)
        if user is None:
            raise LookupError("User not found")
        items = list_prioritized_tasks(user_id)
        false_negative_items = list_false_negative_items(user_id)
        profile = get_profile_snapshot(user_id)
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "user": serialize_user(user),
            "items": items,
            "falseNegativeItems": false_negative_items,
            "profile": profile,
            "availableTags": get_available_tags(user_id),
        }
    )


@api.get("/statistics")
def statistics_snapshot():
    try:
        user_id = get_authenticated_user_id(required=True)
        user = get_user_by_id(user_id)
        if user is None:
            raise LookupError("User not found")
        statistics = get_task_statistics_snapshot(user_id)
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "user": serialize_user(user),
            **statistics,
        }
    )


@api.get("/tasks/profile")
def pipeline_profile():
    try:
        user_id = get_authenticated_user_id(required=True)
        profile = get_profile_snapshot(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(profile)


@api.get("/tasks/recompute-status")
def pipeline_recompute_status():
    try:
        user_id = get_authenticated_user_id(required=True)
        status = get_pipeline_recompute_status(user_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(status)


@api.post("/tasks/<canonical_task_id>/feedback")
def task_feedback(canonical_task_id: str):
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        action = data.get("action")
        if not isinstance(action, str) or not action:
            raise ValueError("action is required.")

        direction = data.get("direction")
        if direction is not None and not isinstance(direction, str):
            raise ValueError("direction must be a string.")

        result = submit_task_feedback(
            user_id,
            canonical_task_id,
            action=action,
            direction=direction,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.patch("/tasks/<canonical_task_id>/tags")
def update_task_card_tags(canonical_task_id: str):
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        result = update_prioritized_task_tags(
            user_id,
            canonical_task_id,
            tags=data.get("tags"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.patch("/tasks/<canonical_task_id>")
def update_task_card(canonical_task_id: str):
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        result = update_prioritized_task(
            user_id,
            canonical_task_id,
            updates=data,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)


@api.delete("/tasks/<canonical_task_id>")
def remove_task_card(canonical_task_id: str):
    try:
        user_id = get_authenticated_user_id(required=True)
        result = remove_prioritized_task(user_id, canonical_task_id)
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(result)
