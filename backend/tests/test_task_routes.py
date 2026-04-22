import unittest
from unittest.mock import patch

from app import create_app
from app.routes import build_token


class TaskRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.headers = {"Authorization": f"Bearer {build_token(7)}"}

    @patch("app.routes.list_prioritized_tasks")
    def test_tasks_route_returns_items(self, list_prioritized_tasks):
        list_prioritized_tasks.return_value = [
            {
                "task_id": "task-1",
                "canonical_task_id": "canon-1",
                "priority_tier": "HIGH",
                "action_window": "TODAY",
                "rationale": "Submission due soon",
                "confidence": 0.72,
                "needs_user_review": False,
            }
        ]

        response = self.client.get("/api/tasks", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["canonical_task_id"], "canon-1")
        list_prioritized_tasks.assert_called_once_with(7)

    @patch("app.routes.get_profile_snapshot")
    @patch("app.routes.list_prioritized_tasks")
    @patch("app.routes.get_user_by_id")
    def test_dashboard_route_returns_bootstrap_payload(
        self,
        get_user_by_id,
        list_prioritized_tasks,
        get_profile_snapshot,
    ):
        get_user_by_id.return_value = {
            "user_id": 7,
            "name": "Avery",
            "email": "avery@example.com",
            "preferences": "School",
        }
        list_prioritized_tasks.return_value = [{"canonical_task_id": "canon-1"}]
        get_profile_snapshot.return_value = {"profile_version": 5}

        response = self.client.get("/api/dashboard", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["user"]["userId"], 7)
        self.assertEqual(payload["items"][0]["canonical_task_id"], "canon-1")
        self.assertEqual(payload["profile"]["profile_version"], 5)

    @patch("app.routes.run_prioritization_for_user")
    def test_task_sync_route_returns_pipeline_summary(self, run_prioritization_for_user):
        run_prioritization_for_user.return_value = {
            "runId": "run-1",
            "rawMessageCount": 4,
            "signalCount": 3,
            "canonicalTaskCount": 2,
            "taskCardCount": 2,
            "items": [],
        }

        response = self.client.post("/api/tasks/sync?limit=20", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["runId"], "run-1")
        run_prioritization_for_user.assert_called_once_with(7, limit=20)

    @patch("app.routes.create_manual_task")
    def test_manual_task_route_returns_payload(self, create_manual_task):
        create_manual_task.return_value = {
            "runId": "run-manual",
            "taskCardCount": 1,
            "items": [{"canonical_task_id": "canon-2"}],
            "profile": {"profile_version": 4},
        }

        response = self.client.post(
            "/api/tasks/manual",
            json={
                "title": "Submit reflection",
                "description": "Due tonight",
                "taskType": "submission",
                "deadlineAt": "2026-04-22T23:59:00",
                "entityName": "CS2103T",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["runId"], "run-manual")
        create_manual_task.assert_called_once_with(
            7,
            title="Submit reflection",
            description="Due tonight",
            task_type="submission",
            deadline_at="2026-04-22T23:59:00",
            entity_name="CS2103T",
        )

    @patch("app.routes.submit_task_feedback")
    def test_task_feedback_route_validates_and_returns_payload(self, submit_task_feedback):
        submit_task_feedback.return_value = {
            "success": True,
            "feedbackEvent": {"canonical_task_id": "canon-1", "action": "WRONG_PRIORITY"},
            "profile": {"profile_version": 2},
        }

        response = self.client.post(
            "/api/tasks/canon-1/feedback",
            json={"action": "WRONG_PRIORITY", "direction": "too_low"},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        submit_task_feedback.assert_called_once_with(
            7,
            "canon-1",
            action="WRONG_PRIORITY",
            direction="too_low",
        )

    @patch("app.routes.get_pipeline_recompute_status")
    def test_recompute_status_route_returns_payload(self, get_pipeline_recompute_status):
        get_pipeline_recompute_status.return_value = {
            "userId": 7,
            "running": True,
            "pending": False,
            "lastRunId": "run-9",
        }

        response = self.client.get("/api/tasks/recompute-status", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["running"])
        get_pipeline_recompute_status.assert_called_once_with(7)

    @patch("app.routes.remove_prioritized_task")
    def test_remove_task_route_returns_payload(self, remove_prioritized_task):
        remove_prioritized_task.return_value = {
            "success": True,
            "canonicalTaskId": "canon-1",
        }

        response = self.client.delete("/api/tasks/canon-1", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        remove_prioritized_task.assert_called_once_with(7, "canon-1")


if __name__ == "__main__":
    unittest.main()
