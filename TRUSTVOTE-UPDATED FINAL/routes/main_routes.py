import os
import sys
from flask import Blueprint, render_template, send_from_directory

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in [BASE_DIR, os.getcwd()]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from config import ID_CARDS_DIR, STORAGE_DIR
except ImportError:
    ID_CARDS_DIR = os.path.join(BASE_DIR, "id_cards")
    STORAGE_DIR = os.path.join(BASE_DIR, "storage")


main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    return render_template('home.html')

@main_bp.route('/id_cards/<path:filename>')
def serve_qr(filename):
    return send_from_directory(ID_CARDS_DIR, filename)

@main_bp.route('/storage/<path:filename>')
def serve_storage(filename):
    return send_from_directory(STORAGE_DIR, filename)

