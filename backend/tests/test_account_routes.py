import unittest
from unittest.mock import patch

from app import create_app
from app.routes import build_token


class AccountRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    @patch("app.routes.get_user_by_email", return_value=None)
    def test_signup_rejects_short_password(self, get_user_by_email):
        response = self.client.post(
            "/api/signup",
            json={"email": "user@example.com", "password": "short", "name": "Taylor"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json(),
            {
                "success": False,
                "error": "Password must be at least 8 characters long.",
            },
        )
        get_user_by_email.assert_not_called()

    @patch("app.routes.get_user_by_email")
    @patch("app.routes.create_user")
    def test_signup_returns_public_user_shape(self, create_user, get_user_by_email):
        get_user_by_email.return_value = None
        create_user.return_value = {
            "user_id": 12,
            "name": "Taylor",
            "email": "user@example.com",
            "preferences": None,
        }

        response = self.client.post(
            "/api/signup",
            json={
                "email": " USER@example.com ",
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
                "email": "user@example.com",
                "preferences": None,
            },
        )
        create_user.assert_called_once()
        self.assertEqual(create_user.call_args.kwargs["name"], "Taylor")
        self.assertEqual(create_user.call_args.kwargs["email"], "user@example.com")
        self.assertTrue(create_user.call_args.kwargs["password_hash"])

    def test_onboarding_rejects_unknown_preference(self):
        token = build_token(5)

        response = self.client.put(
            "/api/onboarding",
            json={"preferences": "Everything"},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json(),
            {"error": "Choose one of the available onboarding options."},
        )


if __name__ == "__main__":
    unittest.main()
