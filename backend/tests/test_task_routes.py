import unittest
from io import BytesIO
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
                "tags": ["assignment", "deadline"],
            }
        ]

        response = self.client.get("/api/tasks", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["canonical_task_id"], "canon-1")
        self.assertEqual(response.get_json()["items"][0]["tags"], ["assignment", "deadline"])
        list_prioritized_tasks.assert_called_once_with(7)

    @patch("app.routes.get_available_tags")
    @patch("app.routes.get_profile_snapshot")
    @patch("app.routes.list_false_negative_items")
    @patch("app.routes.list_prioritized_tasks")
    @patch("app.routes.get_user_by_id")
    def test_dashboard_route_returns_bootstrap_payload(
        self,
        get_user_by_id,
        list_prioritized_tasks,
        list_false_negative_items,
        get_profile_snapshot,
        get_available_tags,
    ):
        get_user_by_id.return_value = {
            "user_id": 7,
            "username": "avery",
            "preferences": "School",
            "performance_time": "Evening",
            "important_topic": "Classes and assignments",
            "prioritise_by": "Urgency",
        }
        list_prioritized_tasks.return_value = [{"canonical_task_id": "canon-1"}]
        list_false_negative_items.return_value = [{"sourceId": "msg-1"}]
        get_profile_snapshot.return_value = {"profile_version": 5}
        get_available_tags.return_value = ["assignment", "urgent"]

        response = self.client.get("/api/dashboard", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["user"]["userId"], 7)
        self.assertEqual(payload["items"][0]["canonical_task_id"], "canon-1")
        self.assertEqual(payload["falseNegativeItems"][0]["sourceId"], "msg-1")
        self.assertEqual(payload["profile"]["profile_version"], 5)
        self.assertEqual(payload["availableTags"], ["assignment", "urgent"])

    @patch("app.routes.get_task_statistics_snapshot")
    @patch("app.routes.get_user_by_id")
    def test_statistics_route_returns_snapshot_payload(
        self,
        get_user_by_id,
        get_task_statistics_snapshot,
    ):
        get_user_by_id.return_value = {
            "user_id": 7,
            "username": "avery",
            "preferences": "School",
            "performance_time": "Evening",
            "important_topic": "Classes and assignments",
            "prioritise_by": "Urgency",
        }
        get_task_statistics_snapshot.return_value = {
            "summary": {
                "totalTaskCards": 3,
                "criticalTasks": 1,
                "highPriorityTasks": 1,
                "dueWithin24Hours": 2,
                "averageConfidence": 0.66,
                "profileConfidence": 0.58,
            },
            "distributions": {
                "priorityTiers": [{"label": "HIGH", "count": 1}],
                "actionWindows": [{"label": "TODAY", "count": 2}],
                "platformMix": [{"label": "gmail", "count": 3}],
            },
            "nearestDeadlines": [{"task_id": "task-1"}],
            "strongestSignals": [{"task_id": "task-2"}],
            "profile": {"profile_version": 9},
        }

        response = self.client.get("/api/statistics", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["user"]["userId"], 7)
        self.assertEqual(payload["summary"]["totalTaskCards"], 3)
        self.assertEqual(payload["distributions"]["platformMix"][0]["label"], "gmail")
        self.assertEqual(payload["nearestDeadlines"][0]["task_id"], "task-1")
        self.assertEqual(payload["strongestSignals"][0]["task_id"], "task-2")
        self.assertEqual(payload["profile"]["profile_version"], 9)
        get_task_statistics_snapshot.assert_called_once_with(7)

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

    @patch("app.routes.schedule_pipeline_recompute")
    def test_async_task_sync_route_returns_scheduled_status(self, schedule_pipeline_recompute):
        schedule_pipeline_recompute.return_value = {
            "userId": 7,
            "running": True,
            "pending": False,
            "lastScheduledAt": "2026-04-25T10:00:00+08:00",
        }

        response = self.client.post("/api/tasks/sync/async?limit=20", headers=self.headers)

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["status"]["running"])
        schedule_pipeline_recompute.assert_called_once_with(
            7,
            refresh_sources=True,
            limit=20,
            reason="manual_refresh",
        )

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
                "tags": ["assignment", "urgent"],
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
            tags=["assignment", "urgent"],
        )

    @patch("app.routes.get_onboarding_context_snapshot")
    @patch("app.routes.get_user_by_id")
    def test_onboarding_context_route_returns_payload(self, get_user_by_id, get_onboarding_context_snapshot):
        get_user_by_id.return_value = {
            "user_id": 7,
            "username": "avery",
            "preferences": "School",
            "performance_time": "Evening",
            "important_topic": "Classes and assignments",
            "prioritise_by": "Urgency",
        }
        get_onboarding_context_snapshot.return_value = {
            "timezone": "Asia/Singapore",
            "busy_windows": [],
            "recurring_task_notes": [],
            "static_preferences": {
                "performance_time": "Evening",
                "important_topic": "Classes and assignments",
                "prioritise_by": "Urgency",
            },
            "calendar_source": None,
        }

        response = self.client.get("/api/onboarding/context", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["user"]["userId"], 7)
        self.assertEqual(payload["user"]["performanceTime"], "Evening")
        self.assertFalse(payload["calendarActive"])

    @patch("app.routes.update_user_onboarding_answers")
    @patch("app.routes.sync_onboarding_context")
    def test_onboarding_route_saves_new_answers(self, sync_onboarding_context, update_user_onboarding_answers):
        update_user_onboarding_answers.return_value = {
            "user_id": 7,
            "username": "avery",
            "preferences": "School",
            "performance_time": "Evening",
            "important_topic": "Classes and assignments",
            "prioritise_by": "Urgency",
        }

        response = self.client.put(
            "/api/onboarding",
            json={
                "performanceTime": "Evening",
                "importantTopic": "Classes and assignments",
                "prioritiseBy": "Urgency",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["user"]["performanceTime"], "Evening")
        update_user_onboarding_answers.assert_called_once_with(
            7,
            performance_time="Evening",
            important_topic="Classes and assignments",
            prioritise_by="Urgency",
        )
        sync_onboarding_context.assert_called_once_with(7)

    @patch("app.routes.save_calendar_context")
    def test_onboarding_calendar_upload_route_returns_payload(self, save_calendar_context):
        save_calendar_context.return_value = {
            "timezone": "Asia/Singapore",
            "busy_windows": [],
            "recurring_task_notes": [],
            "static_preferences": {},
            "calendar_source": {"filename": "class.ics"},
        }

        response = self.client.post(
            "/api/onboarding/calendar",
            data={"file": (BytesIO(b"BEGIN:VCALENDAR\nEND:VCALENDAR"), "class.ics")},
            headers=self.headers,
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["calendarActive"])
        save_calendar_context.assert_called_once()

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

    @patch("app.routes.update_prioritized_task_tags")
    def test_task_tag_update_route_returns_payload(self, update_prioritized_task_tags):
        update_prioritized_task_tags.return_value = {
            "success": True,
            "canonicalTaskId": "canon-1",
            "task": {"canonical_task_id": "canon-1", "tags": ["deadline"]},
            "items": [{"canonical_task_id": "canon-1", "tags": ["deadline"]}],
        }

        response = self.client.patch(
            "/api/tasks/canon-1/tags",
            json={"tags": ["deadline"]},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(response.get_json()["task"]["tags"], ["deadline"])
        update_prioritized_task_tags.assert_called_once_with(
            7,
            "canon-1",
            tags=["deadline"],
        )

    @patch("app.routes.update_prioritized_task")
    def test_task_update_route_returns_payload(self, update_prioritized_task):
        update_prioritized_task.return_value = {
            "success": True,
            "taskId": "canon-1",
            "task": {"canonical_task_id": "canon-1", "task_title": "Updated task"},
            "items": [{"canonical_task_id": "canon-1", "task_title": "Updated task"}],
            "profile": {"profile_version": 6},
            "availableTags": ["deadline", "custom_focus"],
        }

        response = self.client.patch(
            "/api/tasks/canon-1",
            json={
                "title": "Updated task",
                "description": "Fresh details",
                "deadlineAt": "2026-04-24T18:00:00",
                "priorityTier": "HIGH",
                "status": "COMPLETED",
                "tags": ["deadline", "custom_focus"],
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["taskId"], "canon-1")
        self.assertEqual(payload["profile"]["profile_version"], 6)
        update_prioritized_task.assert_called_once_with(
            7,
            "canon-1",
            updates={
                "title": "Updated task",
                "description": "Fresh details",
                "deadlineAt": "2026-04-24T18:00:00",
                "priorityTier": "HIGH",
                "status": "COMPLETED",
                "tags": ["deadline", "custom_focus"],
            },
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
