from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import psycopg2
import bcrypt
import jwt
import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://neondb_owner:npg_VC6NIsHOREy9@ep-square-voice-amr2eqzu-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
db = SQLAlchemy(app)

key = "key"

# class User(db.Model):
#     __tablename__ = "user"
#     __table_args__ = {"schema": "neon_auth"}
#     id = db.Column(db.Uuid, primary_key=True)

class User_Detail(db.Model):
    __tablename__ = "user_details"
    __table_args__ = {"schema": "public"}
    user_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    email = db.Column(db.String)
    password = db.Column(db.String)
    preferences = db.Column(db.String)

# users = User.query.all()
# for u in users:
#     print(u.id)

@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json()
    user = User_Detail.query.filter_by(email=data["email"]).first()

    if not user:
        hashed = bcrypt.hashpw(data["password"].encode("utf-8"), bcrypt.gensalt())
        new_user = User_Detail(name=data["name"],email=data["email"], password=hashed.decode("utf-8"))
        db.session.add(new_user)
        db.session.commit()

        token = jwt.encode(
            {
                "user_id": new_user.user_id, "exp": datetime.datetime.now() + datetime.timedelta(hours=1)
            },
            key,
            algorithm="HS256"
        )
        return jsonify({"success": True, "token": token})

    return jsonify({"success": False})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    user = User_Detail.query.filter_by(email=data["email"]).first()

    print(user)
    if user and bcrypt.checkpw(data["password"].encode("utf-8"), user.password.encode("utf-8")):
        token = jwt.encode(
            {
                "user_id": user.user_id, "exp": datetime.datetime.now() + datetime.timedelta(hours=1)
            },
            key,
            algorithm="HS256"
        )
        return jsonify({"success": True, "token": token})
    
    return jsonify({"success": False})

@app.route("/api/user", methods=["GET"])
def user():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Unauthorised"}), 401
    

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, key, algorithms=["HS256"])
        user_id = payload["user_id"]
        user = User_Detail.query.get(user_id)
        return jsonify({
            "email": user.email,
        })
    
    except jwt.ExpiredSignatureError:
        return jsonify({ "error": "Token expired" }), 401
    
@app.route("/api/onboarding", methods={"PUT"})
def onboarding():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Unauthorised"}), 401
    
    data = request.get_json()
    preferences = data.get("preferences")
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, key, algorithms=["HS256"])
        user_id = payload["user_id"]
        user = User_Detail.query.get(user_id)
        
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        user.preferences = preferences
        db.session.commit()

        return jsonify({"success": True})
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401


@app.route("/")
def home():
    users = User_Detail.query.all()
    print(users)
    return jsonify({
        "user_id": users[0].id,
        # "preferences": users[0].preferences
    })

if __name__ == "__main__":
    app.run(debug=True)