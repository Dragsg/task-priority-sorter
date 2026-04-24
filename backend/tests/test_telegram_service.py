import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from app.telegram_service import (
    get_telegram_settings_payload,
    process_telegram_webhook,
    send_daily_telegram_digest,
    send_instant_telegram_alerts,
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
        summary = send_instant_telegram_alerts(
            6,
            [{"canonical_task_id": "canon-4", "task_title": "Catch up", "priority_tier": "HIGH"}],
        )

        self.assertEqual(summary["sent"], 0)
        self.assertEqual(summary["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
