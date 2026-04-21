import logging
import os
from datetime import datetime, timezone
from threading import Event, Lock, Thread

from .db import list_gmail_link_user_ids, list_outlook_link_user_ids
from .gmail_service import list_new_messages
from .outlook_service import list_new_outlook_messages

logger = logging.getLogger(__name__)

_sync_thread_started = False
_sync_status_lock = Lock()
_sync_status = {
    "last_run_at": None,
    "last_success_at": None,
    "gmail_users_checked": 0,
    "outlook_users_checked": 0,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_background_sync_status() -> dict:
    with _sync_status_lock:
        return dict(_sync_status)


def run_background_email_sync(app):
    run_started_at = _utc_now_iso()

    with _sync_status_lock:
        _sync_status["last_run_at"] = run_started_at

    with app.app_context():
        gmail_user_ids = list_gmail_link_user_ids()
        outlook_user_ids = list_outlook_link_user_ids()

        with _sync_status_lock:
            _sync_status["gmail_users_checked"] = len(gmail_user_ids)
            _sync_status["outlook_users_checked"] = len(outlook_user_ids)

        logger.info(
            "Background email sync tick: gmail_users=%s outlook_users=%s",
            len(gmail_user_ids),
            len(outlook_user_ids),
        )

        for user_id in gmail_user_ids:
            try:
                result = list_new_messages(user_id)
                logger.info(
                    "Background Gmail sync completed for user_id=%s new_messages=%s",
                    user_id,
                    len(result.get("messages", [])),
                )
            except Exception:
                logger.exception("Background Gmail sync failed for user_id=%s", user_id)

        for user_id in outlook_user_ids:
            try:
                result = list_new_outlook_messages(user_id)
                logger.info(
                    "Background Outlook sync completed for user_id=%s new_messages=%s",
                    user_id,
                    len(result.get("messages", [])),
                )
            except Exception:
                logger.exception("Background Outlook sync failed for user_id=%s", user_id)

        with _sync_status_lock:
            _sync_status["last_success_at"] = _utc_now_iso()


def start_background_email_sync(app):
    global _sync_thread_started

    if _sync_thread_started:
        return

    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    interval_seconds = max(60, int(app.config["EMAIL_SYNC_INTERVAL_MINUTES"]) * 60)
    stop_event = Event()

    def worker():
        logger.info(
            "Starting background email sync worker with interval_seconds=%s",
            interval_seconds,
        )
        run_background_email_sync(app)

        while not stop_event.wait(interval_seconds):
            run_background_email_sync(app)

    thread = Thread(
        target=worker,
        name="email-background-sync",
        daemon=True,
    )
    thread.start()
    _sync_thread_started = True
