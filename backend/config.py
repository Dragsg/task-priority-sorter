import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


class Config:
    DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    PORT = int(os.getenv("FLASK_PORT", "5000"))
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    DATABASE_URL = os.getenv("DATABASE_URL")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv(
        "GOOGLE_REDIRECT_URI",
        "http://127.0.0.1:5000/api/gmail/callback",
    )
    GMAIL_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
    ]
    MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
    MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")
    MICROSOFT_REDIRECT_URI = os.getenv(
        "MICROSOFT_REDIRECT_URI",
        "http://localhost:5000/api/outlook/callback",
    )
    MICROSOFT_SCOPES = [
        "openid",
        "profile",
        "offline_access",
        "User.Read",
        "Mail.Read",
    ]
