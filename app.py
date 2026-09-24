# -*- coding: utf-8 -*-
import os
import sys

# Ensure root project directory is in sys.path for Linux / Gunicorn deployment
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in [BASE_DIR, os.getcwd()]:
    if p not in sys.path:
        sys.path.insert(0, p)

from flask import Flask

try:
    from config import TEMPLATE_DIR, STORAGE_DIR, ID_CARDS_DIR, SECRET_KEY
except ImportError:
    TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
    STORAGE_DIR = os.path.join(BASE_DIR, "storage")
    ID_CARDS_DIR = os.path.join(BASE_DIR, "id_cards")
    SECRET_KEY = os.environ.get("SECRET_KEY", "super_secret_trustvote_key")

from database import init_db

# Import Blueprints
from routes.main_routes import main_bp
from routes.register_routes import register_bp
from routes.verify_routes import verify_bp
from routes.vote_routes import vote_bp
from routes.admin_routes import admin_bp
from routes.officer_routes import officer_bp

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. SETUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = 'super_secret_trustvote_key'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024   # 32MB for base64 images
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

# Create necessary directories
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(ID_CARDS_DIR, exist_ok=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. DATABASE INITIALIZATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
init_db()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. REGISTER BLUEPRINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app.register_blueprint(main_bp)
app.register_blueprint(register_bp)
app.register_blueprint(verify_bp)
app.register_blueprint(vote_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(officer_bp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        debug=False,
        host="0.0.0.0",
        port=port
    )