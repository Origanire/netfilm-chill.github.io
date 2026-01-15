from werkzeug.middleware.dispatcher import DispatcherMiddleware
from flask import Flask, jsonify
from flask_cors import CORS

from app_akinator import app as akinator_app
from app_moviegrid import app as moviegrid_app
from app_blindtest import app as blindtest_app

root = Flask(__name__)
CORS(root, resources={r"/*": {"origins": ["*"]}})

@root.get("/health")
def health():
    return jsonify({"status": "ok"})

app = DispatcherMiddleware(root, {
    "/akinator": akinator_app,
    "/moviegrid": moviegrid_app,
    "/blindtest": blindtest_app,
})
