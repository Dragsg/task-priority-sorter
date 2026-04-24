from flask import Flask
from flask_cors import CORS

from config import Config
from .background_sync import start_background_email_sync
from .routes import api
from .telegram_service import ensure_telegram_webhook, get_telegram_startup_warning


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = app.config["SECRET_KEY"]

    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        max_age=600,
    )
    app.register_blueprint(api, url_prefix="/api")
    telegram_warning = get_telegram_startup_warning()
    if telegram_warning:
        app.logger.warning(telegram_warning)
    else:
        try:
            ensure_telegram_webhook()
        except Exception:
            app.logger.exception("Telegram webhook registration failed during startup.")
    start_background_email_sync(app)

    return app
