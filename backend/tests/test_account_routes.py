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
            json={"username": "taylor", "password": "short"},
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
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["user"],
            {
                "userId": 12,
                "username": "taylor",
                "preferences": None,
                "performanceTime": None,
                "importantTopic": None,
                "prioritiseBy": None,
                "onboardingComplete": False,
            },
        )
        create_user.assert_called_once()
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

    @patch("app.routes.get_user_by_username")
    @patch("app.routes.update_user_username")
    def test_update_user_returns_updated_public_shape(self, update_user_username, get_user_by_username):
        token = build_token(5)
        get_user_by_username.return_value = {
            "user_id": 5,
            "username": "new-name",
        }
        update_user_username.return_value = {
            "user_id": 5,
            "username": "new-name",
            "preferences": None,
            "performance_time": "Morning",
            "important_topic": "Personal goals",
            "prioritise_by": "Urgency",
        }

        response = self.client.patch(
            "/api/user",
            json={"username": " new-name "},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "success": True,
                "user": {
                    "userId": 5,
                    "username": "new-name",
                    "preferences": None,
                    "performanceTime": "Morning",
                    "importantTopic": "Personal goals",
                    "prioritiseBy": "Urgency",
                    "onboardingComplete": True,
                },
            },
        )
        get_user_by_username.assert_called_once_with("new-name")
        update_user_username.assert_called_once_with(5, "new-name")

    @patch("app.routes.get_user_by_username", return_value={"user_id": 99, "username": "taken"})
    @patch("app.routes.update_user_username")
    def test_update_user_rejects_duplicate_username(self, update_user_username, get_user_by_username):
        token = build_token(5)

        response = self.client.patch(
            "/api/user",
            json={"username": "taken"},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json(), {"error": "Username already exists"})
        get_user_by_username.assert_called_once_with("taken")
        update_user_username.assert_not_called()

    @patch("app.routes.get_user_by_username")
    @patch("app.routes.update_user_username")
    def test_update_user_rejects_invalid_username(self, update_user_username, get_user_by_username):
        token = build_token(5)

        response = self.client.patch(
            "/api/user",
            json={"username": "ab"},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json(),
            {"error": "Username must be at least 3 characters long."},
        )
        get_user_by_username.assert_not_called()
        update_user_username.assert_not_called()

    @patch("app.routes._start_user_account_deletion")
    @patch("app.routes.get_user_by_id")
    def test_delete_user_rejects_incorrect_confirmation_username(
        self,
        get_user_by_id,
        start_user_account_deletion,
    ):
        token = build_token(5)
        get_user_by_id.return_value = {
            "user_id": 5,
            "username": "taylor",
            "preferences": None,
            "performance_time": "Morning",
            "important_topic": "Personal goals",
            "prioritise_by": "Urgency",
        }

        response = self.client.delete(
            "/api/user",
            json={"username": "wrong-name"},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json(),
            {"error": "Type your current username exactly to confirm account deletion."},
        )
        start_user_account_deletion.assert_not_called()

    @patch("app.routes._start_user_account_deletion")
    @patch("app.routes.get_user_by_id")
    def test_delete_user_removes_account_after_username_confirmation(
        self,
        get_user_by_id,
        start_user_account_deletion,
    ):
        token = build_token(5)
        get_user_by_id.return_value = {
            "user_id": 5,
            "username": "taylor",
            "preferences": None,
            "performance_time": "Morning",
            "important_topic": "Personal goals",
            "prioritise_by": "Urgency",
        }

        response = self.client.delete(
            "/api/user",
            json={"username": " taylor "},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"success": True})
        start_user_account_deletion.assert_called_once_with(5)

    @patch("app.routes.build_google_flow")
    def test_gmail_link_forces_google_account_selection(self, build_google_flow):
        token = build_token(7)
        flow = build_google_flow.return_value
        flow.code_verifier = "code-verifier"
        flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?prompt=select_account",
            "state-123",
        )

        response = self.client.get(
            "/api/gmail/link",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.location,
            "https://accounts.google.com/o/oauth2/auth?prompt=select_account",
        )
        flow.authorization_url.assert_called_once_with(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account consent",
        )
        with self.client.session_transaction() as session_state:
            self.assertEqual(session_state["gmail_oauth_state"], "state-123")
            self.assertEqual(session_state["gmail_code_verifier"], "code-verifier")
            self.assertEqual(session_state["gmail_oauth_user_id"], 7)

    def test_gmail_callback_state_mismatch_redirects_back_to_linking_page(self):
        with self.client.session_transaction() as session_state:
            session_state["gmail_oauth_state"] = "expected-state"
            session_state["gmail_code_verifier"] = "code-verifier"
            session_state["gmail_oauth_user_id"] = 7

        response = self.client.get("/api/gmail/callback?state=wrong-state")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.location,
            "http://localhost:5173/linking?gmail=error&reason=state_mismatch",
        )


if __name__ == "__main__":
    unittest.main()
