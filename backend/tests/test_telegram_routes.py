import unittest
from unittest.mock import patch

from app import create_app
from app.routes import build_token


class TelegramRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.headers = {"Authorization": f"Bearer {build_token(11)}"}

    @patch("app.routes.get_telegram_settings_payload")
    def test_telegram_settings_route_returns_payload(self, get_telegram_settings_payload):
        get_telegram_settings_payload.return_value = {
            "configured": True,
            "configurationError": None,
            "botUsername": "tasksorter_bot",
            "linked": False,
            "linkedChat": None,
            "pendingLink": None,
            "settings": {
                "telegramEnabled": True,
                "instantCritical": True,
                "instantHigh": True,
                "instantMedium": False,
                "instantLow": False,
                "dailyDigestEnabled": True,
                "dailyDigestTime": "08:00",
            },
        }

        response = self.client.get("/api/telegram/settings", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["configured"])
        get_telegram_settings_payload.assert_called_once_with(11)

    @patch("app.routes.update_telegram_settings")
    def test_telegram_settings_update_route_saves_payload(self, update_telegram_settings):
        update_telegram_settings.return_value = {
            "configured": True,
            "configurationError": None,
            "botUsername": "tasksorter_bot",
            "linked": True,
            "linkedChat": {"chatId": "123"},
            "pendingLink": None,
            "settings": {
                "telegramEnabled": True,
                "instantCritical": True,
                "instantHigh": False,
                "instantMedium": False,
                "instantLow": False,
                "dailyDigestEnabled": True,
                "dailyDigestTime": "09:30",
            },
        }

        response = self.client.put(
            "/api/telegram/settings",
            json={
                "telegramEnabled": True,
                "instantCritical": True,
                "instantHigh": False,
                "instantMedium": False,
                "instantLow": False,
                "dailyDigestEnabled": True,
                "dailyDigestTime": "09:30",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["settings"]["dailyDigestTime"], "09:30")
        update_telegram_settings.assert_called_once_with(
            11,
            {
                "telegramEnabled": True,
                "instantCritical": True,
                "instantHigh": False,
                "instantMedium": False,
                "instantLow": False,
                "dailyDigestEnabled": True,
                "dailyDigestTime": "09:30",
            },
        )

    @patch("app.routes.generate_telegram_link_code")
    def test_telegram_link_code_route_generates_code(self, generate_telegram_link_code):
        generate_telegram_link_code.return_value = {
            "configured": True,
            "configurationError": None,
            "botUsername": "tasksorter_bot",
            "linked": False,
            "linkedChat": None,
            "pendingLink": {"code": "TPS-ABCD1234"},
            "settings": {},
        }

        response = self.client.post("/api/telegram/link-code", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["pendingLink"]["code"], "TPS-ABCD1234")
        generate_telegram_link_code.assert_called_once_with(11)


if __name__ == "__main__":
    unittest.main()
