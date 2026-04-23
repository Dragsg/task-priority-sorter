import logging
import os
from threading import Event, Lock, Thread

from .db import list_gmail_link_user_ids, list_outlook_link_user_ids
from .pipeline_bridge import run_background_refresh_for_user
from .time_utils import now_sgt

logger = logging.getLogger(__name__)

_sync_thread_started = False
_sync_status_lock = Lock()
_sync_status = {
    "last_run_at": None,
    "last_success_at": None,
    "gmail_users_checked": 0,
    "outlook_users_checked": 0,
    "linked_users_checked": 0,
    "users_refreshed": 0,
    "users_failed": 0,
    "last_total_task_cards": 0,
}


def _now_iso() -> str:
    return now_sgt().isoformat()


def get_background_sync_status() -> dict:
    with _sync_status_lock:
        return dict(_sync_status)


def run_background_email_sync(app):
    run_started_at = _now_iso()

    with _sync_status_lock:
        _sync_status["last_run_at"] = run_started_at

    with app.app_context():
        gmail_user_ids = set(list_gmail_link_user_ids())
        outlook_user_ids = set(list_outlook_link_user_ids())
        linked_user_ids = sorted(gmail_user_ids | outlook_user_ids)

        with _sync_status_lock:
            _sync_status["gmail_users_checked"] = len(gmail_user_ids)
            _sync_status["outlook_users_checked"] = len(outlook_user_ids)
            _sync_status["linked_users_checked"] = len(linked_user_ids)

        logger.info(
            "Background task refresh tick: linked_users=%s gmail_links=%s outlook_links=%s",
            len(linked_user_ids),
            len(gmail_user_ids),
            len(outlook_user_ids),
        )

        users_refreshed = 0
        users_failed = 0
        total_task_cards = 0

        for user_id in linked_user_ids:
            try:
                result = run_background_refresh_for_user(user_id)
                if result.get("pipelineRan"):
                    users_refreshed += 1
                    total_task_cards += int(result.get("taskCardCount") or 0)
                    logger.info(
                        "Background task refresh completed for user_id=%s raw_messages=%s task_cards=%s",
                        user_id,
                        result.get("rawMessageCount"),
                        result.get("taskCardCount"),
                    )
                else:
                    logger.info(
                        "Background task refresh skipped for user_id=%s reason=%s gmail_fetched=%s outlook_fetched=%s",
                        user_id,
                        result.get("skipReason"),
                        (result.get("emailSync", {}).get("gmail", {}) or {}).get("fetchedCount", 0),
                        (result.get("emailSync", {}).get("outlook", {}) or {}).get("fetchedCount", 0),
                    )
            except Exception:
                users_failed += 1
                logger.exception("Background task refresh failed for user_id=%s", user_id)

        with _sync_status_lock:
            _sync_status["users_refreshed"] = users_refreshed
            _sync_status["users_failed"] = users_failed
            _sync_status["last_total_task_cards"] = total_task_cards
            _sync_status["last_success_at"] = _now_iso()


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
            "Starting background task refresh worker with interval_seconds=%s",
            interval_seconds,
        )
        run_background_email_sync(app)

        while not stop_event.wait(interval_seconds):
            run_background_email_sync(app)

    thread = Thread(
        target=worker,
        name="task-priority-refresh",
        daemon=True,
    )
    thread.start()
    _sync_thread_started = True
