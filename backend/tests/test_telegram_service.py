import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from app.telegram_service import (
    _build_digest_message,
    _build_instant_alert_message,
    _send_message,
    ensure_telegram_webhook,
    get_telegram_settings_payload,
    get_telegram_startup_warning,
    process_telegram_webhook,
    send_daily_telegram_digest,
    send_instant_telegram_alerts,
    send_telegram_test_message,
)

SGT = ZoneInfo("Asia/Singapore")


class TelegramServiceTestCase(unittest.TestCase):
    @patch("app.telegram_service.get_active_telegram_link_code", return_value=None)
    @patch("app.telegram_service.get_telegram_link", return_value=None)
    @patch("app.telegram_service.get_telegram_notification_settings")
    def test_settings_payload_is_safe_when_telegram_not_configured(
        self,
        get_telegram_notification_settings,
        get_telegram_link,
        get_active_telegram_link_code,
    ):
        get_telegram_notification_settings.return_value = {
            "telegram_enabled": True,
            "alert_critical": True,
            "alert_high": True,
            "alert_medium": False,
            "alert_low": False,
            "daily_digest_enabled": True,
            "daily_digest_time": "08:00",
        }

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", ""), patch(
            "app.telegram_service.Config.TELEGRAM_BOT_USERNAME",
            "",
        ):
            payload = get_telegram_settings_payload(5)

        self.assertFalse(payload["configured"])
        self.assertIn("TELEGRAM_BOT_TOKEN", payload["configurationError"])
        self.assertEqual(payload["settings"]["dailyDigestTime"], "08:00")
        get_telegram_link.assert_called_once_with(5)
        get_active_telegram_link_code.assert_called_once_with(5)

    @patch("app.telegram_service._send_message")
    @patch("app.telegram_service.get_user_by_id")
    @patch("app.telegram_service.consume_telegram_link_code")
    def test_webhook_can_complete_linking(
        self,
        consume_telegram_link_code,
        get_user_by_id,
        send_message,
    ):
        consume_telegram_link_code.return_value = {"user_id": 7}
        get_user_by_id.return_value = {"user_id": 7, "username": "avery"}

        payload = {
            "update_id": 1,
            "message": {
                "text": "/start TPS-ABCD1234",
                "chat": {"id": 12345, "type": "private"},
                "from": {"username": "averytg", "first_name": "Avery"},
            },
        }

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"), patch(
            "app.telegram_service.Config.TELEGRAM_WEBHOOK_SECRET",
            "secret",
        ):
            result = process_telegram_webhook(payload, secret_header="secret")

        self.assertTrue(result["linked"])
        consume_telegram_link_code.assert_called_once()
        send_message.assert_called_once_with(
            "12345",
            "Telegram is now linked to avery. You can return to the app and start using alerts.",
        )

    @patch("app.telegram_service.mark_telegram_alert_sent")
    @patch("app.telegram_service._send_message")
    @patch("app.telegram_service.claim_telegram_alert", return_value=True)
    @patch("app.telegram_service.get_telegram_link")
    @patch("app.telegram_service.get_telegram_notification_settings")
    def test_matching_priority_tasks_trigger_alerts(
        self,
        get_telegram_notification_settings,
        get_telegram_link,
        claim_telegram_alert,
        send_message,
        mark_telegram_alert_sent,
    ):
        get_telegram_notification_settings.return_value = {
            "telegram_enabled": True,
            "alert_critical": True,
            "alert_high": True,
            "alert_medium": False,
            "alert_low": False,
            "daily_digest_enabled": True,
            "daily_digest_time": "08:00",
        }
        get_telegram_link.return_value = {"telegram_chat_id": "123"}
        send_message.return_value = {"message_id": 99}
        task = {
            "canonical_task_id": "canon-1",
            "task_title": "Submit lab report",
            "priority_tier": "HIGH",
            "task_description": "Due before tutorial",
            "deadline_at_iso": "2026-04-24T18:00:00+08:00",
            "platforms_seen": ["gmail"],
        }

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"):
            summary = send_instant_telegram_alerts(4, [task])

        self.assertEqual(summary["sent"], 1)
        claim_telegram_alert.assert_called_once_with(
            4,
            canonical_task_id="canon-1",
            priority_tier="HIGH",
            task_payload=task,
        )
        send_message.assert_called_once()
        mark_telegram_alert_sent.assert_called_once_with(
            4,
            canonical_task_id="canon-1",
            message_id="99",
        )

    @patch("app.telegram_service.claim_telegram_alert")
    @patch("app.telegram_service._send_message")
    @patch("app.telegram_service.get_telegram_link")
    @patch("app.telegram_service.get_telegram_notification_settings")
    def test_non_matching_priority_tasks_do_not_trigger_alerts(
        self,
        get_telegram_notification_settings,
        get_telegram_link,
        send_message,
        claim_telegram_alert,
    ):
        get_telegram_notification_settings.return_value = {
            "telegram_enabled": True,
            "alert_critical": True,
            "alert_high": True,
            "alert_medium": False,
            "alert_low": False,
            "daily_digest_enabled": True,
            "daily_digest_time": "08:00",
        }
        get_telegram_link.return_value = {"telegram_chat_id": "123"}

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"):
            summary = send_instant_telegram_alerts(
                4,
                [{"canonical_task_id": "canon-2", "task_title": "Read notes", "priority_tier": "MEDIUM"}],
            )

        self.assertEqual(summary["sent"], 0)
        self.assertEqual(summary["skipped"], 1)
        claim_telegram_alert.assert_not_called()
        send_message.assert_not_called()

    @patch("app.telegram_service.claim_telegram_alert", return_value=False)
    @patch("app.telegram_service._send_message")
    @patch("app.telegram_service.get_telegram_link")
    @patch("app.telegram_service.get_telegram_notification_settings")
    def test_duplicate_alerts_are_not_sent(
        self,
        get_telegram_notification_settings,
        get_telegram_link,
        send_message,
        claim_telegram_alert,
    ):
        get_telegram_notification_settings.return_value = {
            "telegram_enabled": True,
            "alert_critical": True,
            "alert_high": True,
            "alert_medium": False,
            "alert_low": False,
            "daily_digest_enabled": True,
            "daily_digest_time": "08:00",
        }
        get_telegram_link.return_value = {"telegram_chat_id": "123"}

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"):
            summary = send_instant_telegram_alerts(
                4,
                [{"canonical_task_id": "canon-3", "task_title": "Submit quiz", "priority_tier": "CRITICAL"}],
            )

        self.assertEqual(summary["sent"], 0)
        self.assertEqual(summary["skipped"], 1)
        claim_telegram_alert.assert_called_once()
        send_message.assert_not_called()

    @patch("app.telegram_service.mark_telegram_digest_sent")
    @patch("app.telegram_service._send_message")
    @patch("app.telegram_service.claim_telegram_digest", side_effect=[True, False])
    @patch("app.telegram_service.get_telegram_link")
    @patch("app.telegram_service.get_telegram_notification_settings")
    @patch("app.pipeline_bridge.list_prioritized_tasks")
    def test_daily_digest_sends_only_once_per_day(
        self,
        list_prioritized_tasks,
        get_telegram_notification_settings,
        get_telegram_link,
        claim_telegram_digest,
        send_message,
        mark_telegram_digest_sent,
    ):
        get_telegram_notification_settings.return_value = {
            "telegram_enabled": True,
            "alert_critical": True,
            "alert_high": True,
            "alert_medium": False,
            "alert_low": False,
            "daily_digest_enabled": True,
            "daily_digest_time": "08:00",
        }
        get_telegram_link.return_value = {"telegram_chat_id": "123"}
        list_prioritized_tasks.return_value = [
            {
                "canonical_task_id": "canon-1",
                "task_title": "Submit reflection",
                "priority_tier": "HIGH",
                "status": "OPEN",
                "deadline_at_iso": "2026-04-24T17:00:00+08:00",
                "deadline_hours": 2,
            }
        ]
        send_message.return_value = {"message_id": 555}
        now = datetime(2026, 4, 24, 8, 30, tzinfo=SGT)

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"):
            first = send_daily_telegram_digest(9, now=now)
            second = send_daily_telegram_digest(9, now=now)

        self.assertTrue(first)
        self.assertFalse(second)
        send_message.assert_called_once()
        mark_telegram_digest_sent.assert_called_once()
        self.assertEqual(claim_telegram_digest.call_count, 2)

    def test_alerts_do_not_break_when_telegram_is_not_configured(self):
        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", ""):
            summary = send_instant_telegram_alerts(
                6,
                [{"canonical_task_id": "canon-4", "task_title": "Catch up", "priority_tier": "HIGH"}],
            )

        self.assertEqual(summary["sent"], 0)
        self.assertEqual(summary["skipped"], 1)

    def test_startup_warning_when_webhook_url_missing(self):
        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"), patch(
            "app.telegram_service.Config.TELEGRAM_WEBHOOK_URL",
            "",
        ):
            warning = get_telegram_startup_warning()

        self.assertIn("TELEGRAM_WEBHOOK_URL", warning)

    def test_instant_alert_message_uses_html_formatting_and_hosted_link(self):
        task = {
            "task_title": "Submit project proposal",
            "priority_tier": "HIGH",
            "task_description": "Needs review before mentor check-in.",
            "deadline_at_iso": "2026-04-24T18:00:00+08:00",
            "platforms_seen": ["gmail"],
        }

        with patch(
            "app.telegram_service.Config.FRONTEND_URL",
            "https://thankful-stone-0c17fc20f.7.azurestaticapps.net",
        ):
            message = _build_instant_alert_message(task)

        self.assertIn("<b>New task added</b>", message)
        self.assertIn("<b>Submit project proposal</b>", message)
        self.assertNotIn("Why now:", message)
        self.assertIn('<a href="https://thankful-stone-0c17fc20f.7.azurestaticapps.net/kanban">Open app</a>', message)

    def test_digest_message_uses_html_sections_and_hosted_link(self):
        tasks = [
            {
                "task_title": "Submit reflection",
                "priority_tier": "HIGH",
                "task_description": "Wrap this up before class.",
                "deadline_at_iso": "2026-04-24T17:00:00+08:00",
                "deadline_hours": 2,
                "platforms_seen": ["gmail"],
            }
        ]
        now = datetime(2026, 4, 24, 8, 30, tzinfo=SGT)

        with patch(
            "app.telegram_service.Config.FRONTEND_URL",
            "https://thankful-stone-0c17fc20f.7.azurestaticapps.net",
        ):
            message = _build_digest_message(tasks, now)

        self.assertIn("<b>Daily digest</b>", message)
        self.assertIn("<b>Focus first</b>", message)
        self.assertIn("<b>Snapshot</b>", message)
        self.assertNotIn("Why now:", message)
        self.assertIn('<a href="https://thankful-stone-0c17fc20f.7.azurestaticapps.net/kanban">Open app</a>', message)

    @patch("app.telegram_service._send_message")
    @patch("app.pipeline_bridge.list_prioritized_tasks")
    @patch("app.telegram_service.get_telegram_link")
    def test_send_telegram_test_message_sends_todays_digest(
        self,
        get_telegram_link,
        list_prioritized_tasks,
        send_message,
    ):
        get_telegram_link.return_value = {"telegram_chat_id": "123"}
        list_prioritized_tasks.return_value = [
            {
                "task_title": "Submit reflection",
                "priority_tier": "HIGH",
                "status": "OPEN",
                "deadline_at_iso": "2026-04-24T17:00:00+08:00",
                "deadline_hours": 2,
                "platforms_seen": ["gmail"],
            }
        ]
        send_message.return_value = {"message_id": 321}

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"), patch(
            "app.telegram_service.Config.FRONTEND_URL",
            "https://thankful-stone-0c17fc20f.7.azurestaticapps.net",
        ), patch(
            "app.telegram_service.now_sgt",
            return_value=datetime(2026, 4, 24, 8, 30, tzinfo=SGT),
        ):
            result = send_telegram_test_message(7)

        self.assertEqual(result["messageId"], "321")
        sent_message = send_message.call_args.args[1]
        self.assertIn("<b>Daily digest</b>", sent_message)
        self.assertNotIn("Why now:", sent_message)

    @patch("app.telegram_service._send_telegram_api_request")
    def test_send_message_uses_html_parse_mode(self, send_request):
        send_request.return_value = {"ok": True, "result": {"message_id": 1}}

        result = _send_message("123", "<b>Hello</b>")

        self.assertEqual(result["message_id"], 1)
        send_request.assert_called_once_with(
            "sendMessage",
            {
                "chat_id": "123",
                "text": "<b>Hello</b>",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )

    @patch("app.telegram_service._send_telegram_api_request")
    def test_webhook_registration_uses_configured_secret(self, send_request):
        send_request.return_value = {"ok": True, "result": True}

        with patch("app.telegram_service.Config.TELEGRAM_BOT_TOKEN", "token"), patch(
            "app.telegram_service.Config.TELEGRAM_WEBHOOK_URL",
            "https://example.ngrok-free.app/api/telegram/webhook",
        ), patch("app.telegram_service.Config.TELEGRAM_WEBHOOK_SECRET", "secret"):
            response = ensure_telegram_webhook()

        self.assertTrue(response["ok"])
        send_request.assert_called_once_with(
            "setWebhook",
            {
                "url": "https://example.ngrok-free.app/api/telegram/webhook",
                "secret_token": "secret",
            },
        )


if __name__ == "__main__":
    unittest.main()
