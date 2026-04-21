from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, redirect, request, session

from .db import get_gmail_link
from .gmail_service import (
    build_google_flow,
    complete_gmail_link,
    list_new_messages,
    list_recent_messages,
)

api = Blueprint("api", __name__)

PLACEHOLDER_USER_ID = 1


@api.get("/gmail/status")
def gmail_status():
    try:
        link = get_gmail_link(PLACEHOLDER_USER_ID)
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    if not link:
        current_app.logger.info(
            "No Gmail link exists for placeholder user_id=%s",
            PLACEHOLDER_USER_ID,
        )
        return jsonify({"linked": False, "userId": PLACEHOLDER_USER_ID})

    current_app.logger.info(
        "Returning linked Gmail status for placeholder user_id=%s email_address=%s",
        PLACEHOLDER_USER_ID,
        link["email_address"],
    )
    return jsonify(
        {
            "linked": True,
            "userId": PLACEHOLDER_USER_ID,
            "emailAddress": link["email_address"],
            "linkedAt": link["linked_at"].isoformat() if link["linked_at"] else None,
            "historyId": link["history_id"],
        }
    )


@api.get("/gmail/link")
def gmail_link():
    try:
        flow = build_google_flow()
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        session["gmail_oauth_state"] = state
        session["gmail_code_verifier"] = flow.code_verifier
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
        flow = build_google_flow()
        flow.code_verifier = saved_code_verifier
        flow.fetch_token(authorization_response=request.url)
        email_address = complete_gmail_link(PLACEHOLDER_USER_ID, flow)
        session.pop("gmail_oauth_state", None)
        session.pop("gmail_code_verifier", None)
    except Exception as error:
        query = urlencode({"gmail": "error", "reason": str(error)})
        return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")

    query = urlencode({"gmail": "linked", "email": email_address})
    return redirect(f"{current_app.config['FRONTEND_URL']}?{query}")


@api.get("/gmail/messages/recent")
def gmail_recent_messages():
    try:
        result = list_recent_messages(PLACEHOLDER_USER_ID, limit=5)
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(result)


@api.get("/gmail/messages/new")
def gmail_new_messages():
    try:
        result = list_new_messages(PLACEHOLDER_USER_ID)
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(result)
