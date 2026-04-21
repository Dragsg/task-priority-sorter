from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class UserDetail(db.Model):
    __tablename__ = "user_details"

    user_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    preferences = db.Column(db.String(50), nullable=True)
