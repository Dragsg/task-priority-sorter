ALLOWED_PREFERENCES = {"School", "Work", "Personal", "Unsure"}


def serialize_user(user: dict) -> dict:
    return {
        "userId": user["user_id"],
        "name": user["name"],
        "email": user["email"],
        "preferences": user["preferences"],
    }


def normalize_email(value) -> str:
    return (value or "").strip().lower()


def normalize_name(value) -> str:
    return " ".join((value or "").strip().split())


def normalize_preference(value) -> str:
    return (value or "").strip()


def validate_email(email: str):
    if not email:
        raise ValueError("Email is required.")

    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Enter a valid email address.")


def validate_password(password: str):
    if not password:
        raise ValueError("Password is required.")

    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")


def validate_name(name: str):
    if not name:
        raise ValueError("Name is required.")

    if len(name) < 2:
        raise ValueError("Name must be at least 2 characters long.")

    if len(name) > 80:
        raise ValueError("Name must be 80 characters or fewer.")


def validate_preference(preference: str):
    if not preference:
        raise ValueError("Preferences are required.")

    if preference not in ALLOWED_PREFERENCES:
        raise ValueError("Choose one of the available onboarding options.")
