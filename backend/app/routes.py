from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from urllib.parse import urlencode

import bcrypt
import jwt
from flask import Blueprint, current_app, jsonify, redirect, request, session

from config import Config
from .background_sync import get_background_sync_status
from .db import (
    create_user,
    get_gmail_link,
    get_outlook_link,
    get_user_by_email,
    get_user_by_id,
    update_user_preferences,
)
from .pipeline_bridge import (
    create_manual_task,
    get_pipeline_recompute_status,
    get_profile_snapshot,
    list_prioritized_tasks,
    remove_prioritized_task,
    run_prioritization_for_user,
    submit_task_feedback,
    sync_onboarding_context,
)
from .account_utils import (
    normalize_email,
    normalize_name,
    normalize_preference,
    serialize_user,
    validate_email,
    validate_name,
    validate_password,
    validate_preference,
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

api = Blueprint("api", __name__)
ALLOWED_RECENT_LIMITS = {5, 10, 20, 50, 100}


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
    return 400


def get_recent_limit() -> int:
    limit = request.args.get("limit", default=5, type=int)
    if limit not in ALLOWED_RECENT_LIMITS:
        raise RuntimeError("Limit must be one of 5, 10, 20, 50, or 100")
    return limit


@api.post("/signup")
def signup():
    try:
        data = request.get_json() or {}
        email = normalize_email(data.get("email"))
        password = data.get("password") or ""
        name = normalize_name(data.get("name"))

        validate_email(email)
        validate_password(password)
        validate_name(name)

        existing_user = get_user_by_email(email)
        if existing_user:
            return jsonify({"success": False, "error": "Email already exists"}), 409

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
        user = create_user(name=name, email=email, password_hash=password_hash)
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
        email = normalize_email(data.get("email"))
        password = data.get("password") or ""

        validate_email(email)
        if not password:
            raise ValueError("Password is required.")

        user = get_user_by_email(email)
        if not user:
            return jsonify({"success": False, "error": "Invalid email or password"}), 401

        is_valid_password = bcrypt.checkpw(
            password.encode("utf-8"),
            user["password"].encode("utf-8"),
        )
        if not is_valid_password:
            return jsonify({"success": False, "error": "Invalid email or password"}), 401

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


@api.put("/onboarding")
def onboarding():
    try:
        user_id = get_authenticated_user_id(required=True)
        data = request.get_json() or {}
        preferences = normalize_preference(data.get("preferences"))
        validate_preference(preferences)

        user = update_user_preferences(user_id, preferences)
        if not user:
            return jsonify({"error": "User not found"}), 404
        sync_onboarding_context(user_id, preferences)
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
            prompt="consent",
        )
        session["gmail_oauth_state"] = state
        session["gmail_code_verifier"] = flow.code_verifier
        session["gmail_oauth_user_id"] = user_id
        return redirect(authorization_url)
    except Exception as error:
        query = urlencode({"gmail": "error", "reason": str(error)})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")


@api.get("/gmail/callback")
def gmail_callback():
    if request.args.get("error"):
        query = urlencode({"gmail": "error", "reason": request.args["error"]})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")

    saved_state = session.get("gmail_oauth_state")
    saved_code_verifier = session.get("gmail_code_verifier")
    incoming_state = request.args.get("state")
    if not saved_state or saved_state != incoming_state:
        query = urlencode({"gmail": "error", "reason": "state_mismatch"})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")

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
        query = urlencode({"gmail": "error", "reason": str(error)})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")

    query = urlencode({"gmail": "linked", "email": email_address})
    return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")


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


@api.post("/tasks/sync")
def sync_prioritized_tasks():
    try:
        user_id = get_authenticated_user_id(required=True)
        limit = request.args.get("limit", default=None, type=int)
        result = run_prioritization_for_user(user_id, limit=limit)
    except Exception as error:
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
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify({"items": items})


@api.get("/dashboard")
def dashboard_bootstrap():
    try:
        user_id = get_authenticated_user_id(required=True)
        user = get_user_by_id(user_id)
        if user is None:
            raise LookupError("User not found")
        items = list_prioritized_tasks(user_id)
        profile = get_profile_snapshot(user_id)
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), get_status_code(error)

    return jsonify(
        {
            "user": serialize_user(user),
            "items": items,
            "profile": profile,
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
        result = submit_task_feedback(
            user_id,
            canonical_task_id,
            action=data.get("action"),
            direction=data.get("direction"),
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
