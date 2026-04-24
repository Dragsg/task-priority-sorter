from pipeline.models import PrioritizedTaskCard
from pipeline.models.enums import ActionWindow, PriorityTier
from pipeline.storage.repositories import _sort_task_cards


def _build_card(
    canonical_task_id: str,
    *,
    priority_tier: PriorityTier,
    deadline_hours: float | None,
    task_title: str,
) -> PrioritizedTaskCard:
    return PrioritizedTaskCard(
        task_id=f"task-{canonical_task_id}",
        canonical_task_id=canonical_task_id,
        user_id="user-1",
        run_id="run-1",
        priority_tier=priority_tier,
        action_window=ActionWindow.TODAY,
        rationale="Testing board order",
        confidence=0.8,
        needs_user_review=False,
        deadline_hours=deadline_hours,
        task_title=task_title,
    )


def test_sort_task_cards_orders_by_priority_deadline_title_and_task_id():
    cards = [
        _build_card("canon-z", priority_tier=PriorityTier.HIGH, deadline_hours=6, task_title="Write summary"),
        _build_card("canon-a", priority_tier=PriorityTier.CRITICAL, deadline_hours=12, task_title="B task"),
        _build_card("canon-b", priority_tier=PriorityTier.CRITICAL, deadline_hours=12, task_title="A task"),
        _build_card("canon-c", priority_tier=PriorityTier.MEDIUM, deadline_hours=None, task_title="Alpha"),
        _build_card("canon-d", priority_tier=PriorityTier.MEDIUM, deadline_hours=None, task_title="Alpha"),
    ]

    ordered = _sort_task_cards(cards)

    assert [card.canonical_task_id for card in ordered] == [
        "canon-b",
        "canon-a",
        "canon-z",
        "canon-c",
        "canon-d",
    ]
