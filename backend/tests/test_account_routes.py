import unittest
from unittest.mock import patch

from app import create_app
from app.routes import build_token


class AccountRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    @patch("app.routes.get_user_by_username", return_value=None)
    def test_signup_rejects_short_password(self, get_user_by_username):
        response = self.client.post(
            "/api/signup",
            json={"username": "taylor", "password": "short", "name": "Taylor"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json(),
            {
                "success": False,
                "error": "Password must be at least 8 characters long.",
            },
        )
        get_user_by_username.assert_not_called()

    @patch("app.routes.get_user_by_username")
    @patch("app.routes.create_user")
    def test_signup_returns_public_user_shape(self, create_user, get_user_by_username):
        get_user_by_username.return_value = None
        create_user.return_value = {
            "user_id": 12,
            "name": "Taylor",
            "username": "taylor",
            "preferences": None,
            "performance_time": None,
            "important_topic": None,
            "prioritise_by": None,
        }

        response = self.client.post(
            "/api/signup",
            json={
                "username": " taylor ",
                "password": "long-enough",
                "name": " Taylor ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["user"],
            {
                "userId": 12,
                "name": "Taylor",
                "username": "taylor",
                "preferences": None,
                "performanceTime": None,
                "importantTopic": None,
                "prioritiseBy": None,
                "onboardingComplete": False,
            },
        )
        create_user.assert_called_once()
        self.assertEqual(create_user.call_args.kwargs["name"], "Taylor")
        self.assertEqual(create_user.call_args.kwargs["username"], "taylor")
        self.assertTrue(create_user.call_args.kwargs["password_hash"])

    def test_onboarding_rejects_unknown_performance_time(self):
        token = build_token(5)

        response = self.client.put(
            "/api/onboarding",
            json={
                "performanceTime": "Whenever",
                "importantTopic": "Classes and assignments",
                "prioritiseBy": "Urgency",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json(),
            {"error": "Choose one of the available performance time options."},
        )


if __name__ == "__main__":
    unittest.main()
