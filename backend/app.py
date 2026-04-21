import datetime as dt
import os

import bcrypt
import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS

from config import Config
from models import UserDetail, db


PREFERENCE_OPTIONS = {"School", "Work", "Personal", "Unsure"}


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,
    )
    db.init_app(app)

    with app.app_context():
        db.create_all()

    register_routes(app)
    return app


def register_routes(app):
    @app.route("/api/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok"})

    @app.route("/api/auth/signup", methods=["POST"])
    def signup():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        email = normalize_email(data.get("email"))
        password = data.get("password") or ""

        if not name:
            return error_response("Please enter your name.", 400)
        if not email:
            return error_response("Please enter a valid email address.", 400)
        if len(password) < 8:
            return error_response("Password must be at least 8 characters.", 400)

        existing_user = UserDetail.query.filter_by(email=email).first()
        if existing_user:
            return error_response("An account with that email already exists.", 409)

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

        user = UserDetail(name=name, email=email, password=password_hash)
        db.session.add(user)
        db.session.commit()

        token = create_token(app, user.user_id)
        return (
            jsonify(
                {
                    "success": True,
                    "token": token,
                    "user": serialize_user(user),
                }
            ),
            201,
        )

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        password = data.get("password") or ""

        if not email or not password:
            return error_response("Email and password are required.", 400)

        user = UserDetail.query.filter_by(email=email).first()
        if not user or not bcrypt.checkpw(
            password.encode("utf-8"),
            user.password.encode("utf-8"),
        ):
            return error_response("Invalid email or password.", 401)

        token = create_token(app, user.user_id)
        return jsonify(
            {
                "success": True,
                "token": token,
                "user": serialize_user(user),
            }
        )

    @app.route("/api/auth/me", methods=["GET"])
    def current_user():
        user, error = get_authenticated_user(app)
        if error:
            return error

        return jsonify({"success": True, "user": serialize_user(user)})

    @app.route("/api/onboarding", methods=["PUT"])
    def save_onboarding():
        user, error = get_authenticated_user(app)
        if error:
            return error

        data = request.get_json(silent=True) or {}
        preference = data.get("preference")

        if preference not in PREFERENCE_OPTIONS:
            return error_response("Please choose one of the onboarding options.", 400)

        user.preferences = preference
        db.session.commit()

        return jsonify({"success": True, "user": serialize_user(user)})


def normalize_email(value):
    if not value or "@" not in value:
        return ""
    return value.strip().lower()


def create_token(app, user_id):
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        hours=app.config["JWT_EXPIRATION_HOURS"]
    )
    return jwt.encode(
        {"user_id": user_id, "exp": expires_at},
        app.config["JWT_SECRET_KEY"],
        algorithm="HS256",
    )


def get_authenticated_user(app):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, error_response("Authorization token is missing.", 401)

    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token,
            app.config["JWT_SECRET_KEY"],
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        return None, error_response("Your session has expired. Please log in again.", 401)
    except jwt.InvalidTokenError:
        return None, error_response("Invalid authorization token.", 401)

    user = db.session.get(UserDetail, payload.get("user_id"))
    if not user:
        return None, error_response("User not found.", 404)

    return user, None


def serialize_user(user):
    return {
        "user_id": user.user_id,
        "name": user.name,
        "email": user.email,
        "preference": user.preferences,
        "has_completed_onboarding": bool(user.preferences),
    }


def error_response(message, status_code):
    return jsonify({"success": False, "message": message}), status_code


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=True, port=port)
