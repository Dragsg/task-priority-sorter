from flask import Flask
from flask_cors import CORS

from config import Config
from .background_sync import start_background_email_sync
from .routes import api


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = app.config["SECRET_KEY"]

    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
    app.register_blueprint(api, url_prefix="/api")
    start_background_email_sync(app)

    return app
