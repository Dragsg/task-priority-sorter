ALLOWED_PERFORMANCE_TIMES = {
    "Morning",
    "Afternoon",
    "Evening",
    "It depends",
}
ALLOWED_IMPORTANT_TOPICS = {
    "Classes and assignments",
    "External meetings and events",
    "Personal goals",
    "A mix of these",
}
ALLOWED_PRIORITISE_BY = {
    "Urgency",
    "Overall importance",
    "Who it's from",
    "A mix of these",
}


def serialize_user(user: dict) -> dict:
    return {
        "userId": user["user_id"],
        "username": user["username"],
        "preferences": user["preferences"],
        "performanceTime": user.get("performance_time"),
        "importantTopic": user.get("important_topic"),
        "prioritiseBy": user.get("prioritise_by"),
        "onboardingComplete": is_onboarding_complete(user),
    }


def normalize_username(value) -> str:
    return (value or "").strip()


def normalize_preference(value) -> str:
    return (value or "").strip()


def normalize_performance_time(value) -> str:
    return _normalize_onboarding_choice(
        value,
        {
            "morning": "Morning",
            "afternoon": "Afternoon",
            "evening": "Evening",
            "depends": "It depends",
            "it depends": "It depends",
        },
    )


def normalize_important_topic(value) -> str:
    return _normalize_onboarding_choice(
        value,
        {
            "classes and assignments": "Classes and assignments",
            "external meetings and events": "External meetings and events",
            "personal goals": "Personal goals",
            "mix": "A mix of these",
            "a mix of these": "A mix of these",
        },
    )


def normalize_prioritise_by(value) -> str:
    return _normalize_onboarding_choice(
        value,
        {
            "urgency": "Urgency",
            "overall importance": "Overall importance",
            "who it's from": "Who it's from",
            "mix": "A mix of these",
            "a mix of these": "A mix of these",
        },
    )


def _normalize_onboarding_choice(value, mapping: dict[str, str]) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    return mapping.get(cleaned.lower(), cleaned)


def validate_username(username: str):
    cleaned = username.strip()

    if not cleaned:
        raise ValueError("Username is required.")

    if len(cleaned) < 3:
        raise ValueError("Username must be at least 3 characters long.")

    if len(cleaned) > 40:
        raise ValueError("Username must be 40 characters or fewer.")


def validate_password(password: str):
    if not password:
        raise ValueError("Password is required.")

    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")


def validate_preference(preference: str):
    if not preference:
        raise ValueError("Preferences are required.")

    if preference not in {"School", "Work", "Personal", "Unsure"}:
        raise ValueError("Choose one of the available onboarding options.")


def validate_performance_time(performance_time: str):
    if not performance_time:
        raise ValueError("Choose when it is easiest for you to get important work done.")

    if performance_time not in ALLOWED_PERFORMANCE_TIMES:
        raise ValueError("Choose one of the available performance time options.")


def validate_important_topic(important_topic: str):
    if not important_topic:
        raise ValueError("Choose which topic or area matters most right now.")

    if important_topic not in ALLOWED_IMPORTANT_TOPICS:
        raise ValueError("Choose one of the available important topic options.")


def validate_prioritise_by(prioritise_by: str):
    if not prioritise_by:
        raise ValueError("Choose what should matter most when the system prioritises tasks.")

    if prioritise_by not in ALLOWED_PRIORITISE_BY:
        raise ValueError("Choose one of the available prioritisation options.")


def is_onboarding_complete(user: dict | None) -> bool:
    if not user:
        return False

    return bool(
        user.get("performance_time")
        and user.get("important_topic")
        and user.get("prioritise_by")
    )
