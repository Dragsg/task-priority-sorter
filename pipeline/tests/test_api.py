from fastapi.testclient import TestClient

from pipeline.api import create_app
from pipeline.storage.repositories import InMemoryPipelineRepository


def test_api_end_to_end_ingest_run_read_and_feedback():
    repository = InMemoryPipelineRepository()
    app = create_app(repository=repository)
    client = TestClient(app)

    onboarding_response = client.put(
        "/users/user-1/onboarding-context",
        json={
            "user_id": "ignored-by-path",
            "timezone": "Asia/Singapore",
            "timetable_summary": "Evenings are best",
            "busy_windows": [],
            "recurring_task_notes": [],
            "static_preferences": {},
        },
    )
    assert onboarding_response.status_code == 200
    assert onboarding_response.json()["user_id"] == "user-1"

    alias_response = client.put(
        "/users/user-1/entity-aliases",
        json={
            "aliases": [
                {
                    "alias_key": "cs2103t",
                    "canonical_entity_key": "cs2103t",
                    "canonical_entity_name": "CS2103T",
                    "entity_type": "module",
                }
            ]
        },
    )
    assert alias_response.status_code == 200
    assert alias_response.json() == {"alias_count": 1}

    ingest_response = client.post(
        "/users/user-1/raw-messages",
        json={
            "messages": [
                {
                    "user_id": "ignored-by-path",
                    "platform": "gmail",
                    "source_id": "msg-1",
                    "subject": "CS2103T project due tonight",
                    "body_text": "Submit the CS2103T project by tonight 11:59pm.",
                    "sender_id": "prof.chen",
                    "sender_display": "Prof Chen",
                    "sender_email": "chen@school.edu",
                    "sender_domain": "school.edu",
                },
                {
                    "user_id": "ignored-by-path",
                    "platform": "teams",
                    "source_id": "msg-2",
                    "body_text": "Reminder: CS2103T project due tonight",
                    "sender_id": "prof.chen",
                    "sender_display": "Prof Chen",
                },
            ]
        },
    )
    assert ingest_response.status_code == 200
    assert ingest_response.json() == {"message_count": 2}

    run_response = client.post("/users/user-1/pipeline/run")
    assert run_response.status_code == 200
    assert run_response.json()["raw_message_count"] == 2
    assert run_response.json()["task_card_count"] == 1

    cards_response = client.get("/users/user-1/task-cards")
    assert cards_response.status_code == 200
    cards = cards_response.json()["items"]
    assert len(cards) == 1
    assert cards[0]["entity_name"] == "CS2103T"
    canonical_task_id = cards[0]["canonical_task_id"]

    feedback_response = client.post(
        f"/users/user-1/task-cards/{canonical_task_id}/feedback",
        json={"action": "WRONG_PRIORITY", "direction": "too_low"},
    )
    assert feedback_response.status_code == 200
    feedback_payload = feedback_response.json()
    assert feedback_payload["feedback_event"]["canonical_task_id"] == canonical_task_id
    assert feedback_payload["profile"]["profile_version"] == 2
    assert feedback_payload["profile"]["entity_weights"]["cs2103t"]["priority_multiplier"] >= 1.1

    profile_response = client.get("/users/user-1/profile")
    assert profile_response.status_code == 200
    assert profile_response.json()["profile_version"] == 2
