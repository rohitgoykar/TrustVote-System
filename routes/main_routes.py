import os
from flask import Blueprint, render_template, send_from_directory
from config import ID_CARDS_DIR

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    return render_template('home.html')

@main_bp.route('/id_cards/<path:filename>')
def serve_qr(filename):
    return send_from_directory(ID_CARDS_DIR, filename)
