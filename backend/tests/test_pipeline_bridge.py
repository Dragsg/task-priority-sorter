import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.pipeline_bridge import (
    _build_dashboard_items,
    create_manual_task,
    get_task_statistics_snapshot,
    refresh_linked_email_sources,
    _run_pipeline_from_stored_messages,
)
from pipeline.models import TaskStatus


class PipelineBridgeTestCase(unittest.TestCase):
    def test_build_dashboard_items_includes_accepted_cards_for_kanban(self):
        repository = MagicMock()
        pending_card = MagicMock()
        accepted_card = MagicMock()
        completed_card = MagicMock()
        pending_card.model_dump.return_value = {
            "canonical_task_id": "queue-1",
            "status": "pending_review",
        }
        accepted_card.model_dump.return_value = {
            "canonical_task_id": "board-1",
            "status": "accepted",
        }
        completed_card.model_dump.return_value = {
            "canonical_task_id": "done-1",
            "status": "completed",
        }
        repository.get_current_task_cards.return_value = [pending_card]
        repository.get_accepted_task_cards.return_value = [accepted_card]
        repository.get_completed_task_cards.return_value = [completed_card]

        items = _build_dashboard_items(repository, 77)

        self.assertEqual(
            [item["status"] for item in items],
            ["pending_review", "accepted", "completed"],
        )

    @patch("app.pipeline_bridge.uuid4")
    @patch("app.pipeline_bridge._build_dashboard_items")
    @patch("app.pipeline_bridge._apply_profile_feedback")
    @patch("app.pipeline_bridge._run_pipeline_from_stored_messages")
    @patch("app.pipeline_bridge.get_user_by_id")
    @patch("app.pipeline_bridge.save_messages")
    @patch("app.pipeline_bridge.get_pipeline_repository")
    def test_create_manual_task_auto_accepts_new_board_task(
        self,
        get_pipeline_repository,
        save_messages,
        get_user_by_id,
        run_pipeline_from_stored_messages,
        apply_profile_feedback,
        build_dashboard_items,
        uuid4,
    ):
        repository = MagicMock()
        get_pipeline_repository.return_value = repository
        uuid4.return_value = SimpleNamespace(hex="manual-card")
        get_user_by_id.return_value = {"username": "avery"}
        run_pipeline_from_stored_messages.return_value = {"items": []}
        repository.get_current_task_cards.return_value = [
            SimpleNamespace(
                canonical_task_id="manual-canon-1",
                evidence_source_ids=["manual-manual-card"],
            )
        ]
        repository.get_feedback_update_context.return_value = SimpleNamespace(
            task=SimpleNamespace(canonical_task_id="manual-canon-1")
        )
        updated_profile = MagicMock()
        updated_profile.model_dump.return_value = {"profile_version": 6}
        apply_profile_feedback.return_value = (updated_profile, SimpleNamespace())
        build_dashboard_items.return_value = [
            {"canonical_task_id": "manual-canon-1", "status": "accepted"}
        ]

        result = create_manual_task(
            7,
            title="Submit reflection",
            description="Due tonight",
            task_type="submission",
            deadline_at="2026-04-24T23:59:00+08:00",
            entity_name="CS2103T",
            tags=["assignment"],
        )

        save_messages.assert_called_once()
        repository.get_feedback_update_context.assert_called_once_with("7", "manual-canon-1")
        repository.apply_task_action.assert_called_once()
        action_call = repository.apply_task_action.call_args
        self.assertEqual(action_call.args[:2], ("7", "manual-canon-1"))
        self.assertEqual(action_call.kwargs["action"].value, "ACCEPT")
        build_dashboard_items.assert_called_once_with(repository, 7)
        self.assertEqual(result["items"], build_dashboard_items.return_value)
        self.assertEqual(result["profile"], {"profile_version": 6})
        self.assertEqual(result["manualTaskCanonicalTaskId"], "manual-canon-1")
        self.assertEqual(result["manualTaskSourceId"], "manual-manual-card")

    @patch("app.pipeline_bridge.logger")
    @patch("app.pipeline_bridge.get_profile_snapshot")
    @patch("app.pipeline_bridge.get_available_tags")
    @patch("app.pipeline_bridge._build_dashboard_items")
    @patch("app.pipeline_bridge._row_to_raw_message")
    @patch("app.pipeline_bridge.list_stored_messages")
    @patch("app.pipeline_bridge.get_pipeline_repository")
    @patch("app.pipeline_bridge.get_priority_pipeline")
    @patch("app.pipeline_bridge.sync_onboarding_context")
    def test_run_pipeline_from_stored_messages_counts_new_non_rejected_task_cards(
        self,
        sync_onboarding_context,
        get_priority_pipeline,
        get_pipeline_repository,
        list_stored_messages,
        row_to_raw_message,
        build_dashboard_items,
        get_available_tags,
        get_profile_snapshot,
        logger,
    ):
        repository = MagicMock()
        pipeline = get_priority_pipeline.return_value
        get_pipeline_repository.return_value = repository
        list_stored_messages.return_value = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
        row_to_raw_message.side_effect = ["raw-1", "raw-2", "raw-3"]
        build_dashboard_items.return_value = [
            {"canonical_task_id": "old-open", "status": "pending_review"},
            {"canonical_task_id": "old-completed", "status": "completed"},
            {"canonical_task_id": "run-open", "status": "pending_review"},
            {"canonical_task_id": "run-completed", "status": "completed"},
        ]
        get_available_tags.return_value = ["assignment"]
        get_profile_snapshot.return_value = {"profile_version": 9}
        pipeline.run_messages.return_value = SimpleNamespace(
            run_id="run-1",
            profile=None,
            decisions=[],
            signals=["signal-1", "signal-2"],
            canonical_tasks=["task-1"],
            task_cards=[
                SimpleNamespace(canonical_task_id="run-open", status=TaskStatus.PENDING_REVIEW),
                SimpleNamespace(canonical_task_id="run-rejected", status=TaskStatus.PENDING_REVIEW),
                SimpleNamespace(canonical_task_id="run-completed", status=TaskStatus.PENDING_REVIEW),
            ],
        )
        repository.get_feedback_task_context.side_effect = [
            SimpleNamespace(status=TaskStatus.PENDING_REVIEW),
            SimpleNamespace(status=TaskStatus.REJECTED),
            SimpleNamespace(status=TaskStatus.COMPLETED),
        ]

        result = _run_pipeline_from_stored_messages(14, refresh_sources=False)

        sync_onboarding_context.assert_called_once_with(14)
        pipeline.run_messages.assert_called_once_with("14", ["raw-1", "raw-2", "raw-3"])
        self.assertEqual(result["rawMessageCount"], 3)
        self.assertEqual(result["signalCount"], 2)
        self.assertEqual(result["canonicalTaskCount"], 1)
        self.assertEqual(result["taskCardCount"], 1)
        self.assertEqual(result["items"], build_dashboard_items.return_value)
        self.assertEqual(result["profile"], {"profile_version": 9})
        logger.info.assert_called_once_with(
            "Prioritization run user_id=%s emails_scanned=%s non_task_emails=%s new_cards=%s provider=%s run_id=%s",
            14,
            3,
            1,
            1,
            "unknown",
            "run-1",
        )

    @patch("app.pipeline_bridge.list_new_outlook_messages")
    @patch("app.pipeline_bridge.list_recent_outlook_messages")
    @patch("app.pipeline_bridge.list_new_messages")
    @patch("app.pipeline_bridge.list_recent_messages")
    @patch("app.pipeline_bridge.get_outlook_link")
    @patch("app.pipeline_bridge.get_gmail_link")
    def test_refresh_linked_email_sources_calls_provider_sync_functions(
        self,
        get_gmail_link,
        get_outlook_link,
        list_recent_messages,
        list_new_messages,
        list_recent_outlook_messages,
        list_new_outlook_messages,
    ):
        get_gmail_link.return_value = {"history_id": "123"}
        get_outlook_link.return_value = {"last_received_at": None}
        list_new_messages.return_value = {"messages": [{"id": "g1"}, {"id": "g2"}]}
        list_recent_outlook_messages.return_value = {"messages": [{"id": "o1"}]}

        summary = refresh_linked_email_sources(11, recent_limit=25)

        list_new_messages.assert_called_once_with(11, link={"history_id": "123"})
        list_recent_outlook_messages.assert_called_once_with(11, limit=25)
        list_recent_messages.assert_not_called()
        list_new_outlook_messages.assert_not_called()
        self.assertEqual(summary["gmail"]["mode"], "new")
        self.assertEqual(summary["gmail"]["fetchedCount"], 2)
        self.assertEqual(summary["outlook"]["mode"], "recent")
        self.assertEqual(summary["outlook"]["fetchedCount"], 1)

    @patch("app.pipeline_bridge.get_profile_snapshot")
    @patch("app.pipeline_bridge.list_prioritized_tasks")
    def test_get_task_statistics_snapshot_aggregates_current_user_task_cards(
        self,
        list_prioritized_tasks,
        get_profile_snapshot,
    ):
        list_prioritized_tasks.return_value = [
            {
                "task_id": "task-1",
                "canonical_task_id": "canon-1",
                "priority_tier": "CRITICAL",
                "action_window": "NOW",
                "confidence": 0.95,
                "deadline_hours": 2,
                "platforms_seen": ["gmail"],
                "task_title": "Pay fee",
                "rationale": "Overdue soon",
            },
            {
                "task_id": "task-2",
                "canonical_task_id": "canon-2",
                "priority_tier": "HIGH",
                "action_window": "TODAY",
                "confidence": 0.7,
                "deadline_hours": 18,
                "platforms_seen": ["outlook"],
                "task_title": "Submit form",
                "rationale": "Due today",
            },
            {
                "task_id": "task-3",
                "canonical_task_id": "canon-3",
                "priority_tier": "LOW",
                "action_window": "THIS_WEEK",
                "confidence": 0.5,
                "deadline_hours": 72,
                "platforms_seen": [],
                "task_title": "Read newsletter",
                "rationale": "Can wait",
            },
        ]
        get_profile_snapshot.return_value = {"confidence": 0.61, "profile_version": 4}

        snapshot = get_task_statistics_snapshot(14)

        self.assertEqual(snapshot["summary"]["totalTaskCards"], 3)
        self.assertEqual(snapshot["summary"]["criticalTasks"], 1)
        self.assertEqual(snapshot["summary"]["highPriorityTasks"], 1)
        self.assertEqual(snapshot["summary"]["dueWithin24Hours"], 2)
        self.assertAlmostEqual(snapshot["summary"]["averageConfidence"], (0.95 + 0.7 + 0.5) / 3)
        self.assertEqual(snapshot["summary"]["profileConfidence"], 0.61)
        self.assertEqual(
            snapshot["distributions"]["priorityTiers"],
            [
                {"label": "CRITICAL", "count": 1},
                {"label": "HIGH", "count": 1},
                {"label": "LOW", "count": 1},
            ],
        )
        self.assertEqual(
            snapshot["distributions"]["actionWindows"],
            [
                {"label": "NOW", "count": 1},
                {"label": "THIS_WEEK", "count": 1},
                {"label": "TODAY", "count": 1},
            ],
        )
        self.assertEqual(
            snapshot["distributions"]["platformMix"],
            [
                {"label": "email", "count": 1},
                {"label": "gmail", "count": 1},
                {"label": "outlook", "count": 1},
            ],
        )
        self.assertEqual(
            [task["task_id"] for task in snapshot["nearestDeadlines"]],
            ["task-1", "task-2", "task-3"],
        )
        self.assertEqual(
            [task["task_id"] for task in snapshot["strongestSignals"]],
            ["task-1", "task-2", "task-3"],
        )
        self.assertEqual(snapshot["profile"]["profile_version"], 4)
        list_prioritized_tasks.assert_called_once_with(14)
        get_profile_snapshot.assert_called_once_with(14)


if __name__ == "__main__":
    unittest.main()
