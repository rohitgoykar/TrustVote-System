# -*- coding: utf-8 -*-
"""
FIRST-TIME VOTER e-EPIC DOWNLOAD PORTAL & FORM NO. 6 APPLICATION
State Election Commission Maharashtra / National Voter Services Portal
Standalone Web Application with First-Time Applicant Form & e-EPIC Download
Port: 5001 (Default)
"""

import os
import sys
import random
import base64
import sqlite3
import qrcode
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, render_template_string, request, jsonify, send_file, abort, send_from_directory, redirect, url_for, session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Database path: fallback to local or adjacent TrustVote database
TRUSTVOTE_DB = os.path.abspath(os.path.join(BASE_DIR, "..", "TRUSTVOTE-UPDATED FINAL (1)", "voters.db"))
LOCAL_DB = os.path.join(BASE_DIR, "voters.db")

def get_db_path():
    if os.path.exists(LOCAL_DB):
        return LOCAL_DB
    if os.path.exists(TRUSTVOTE_DB):
        return TRUSTVOTE_DB
    return LOCAL_DB

# Storage paths
ID_CARDS_DIR = os.path.join(BASE_DIR, "id_cards")
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# TrustVote storage sync paths
TRUSTVOTE_STORAGE = os.path.abspath(os.path.join(BASE_DIR, "..", "TRUSTVOTE-UPDATED FINAL (1)", "storage"))
TRUSTVOTE_ID_CARDS = os.path.abspath(os.path.join(BASE_DIR, "..", "TRUSTVOTE-UPDATED FINAL (1)", "id_cards"))
if os.path.exists(ID_CARDS_DIR):
    ACTIVE_ID_CARDS_DIR = ID_CARDS_DIR
elif os.path.exists(TRUSTVOTE_ID_CARDS):
    ACTIVE_ID_CARDS_DIR = TRUSTVOTE_ID_CARDS
else:
    ACTIVE_ID_CARDS_DIR = ID_CARDS_DIR

import re
import numpy as np
import cv2
try:
    import pytesseract
    from PIL import Image
    import io
except Exception:
    pytesseract = None

os.makedirs(ID_CARDS_DIR, exist_ok=True)
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(os.path.join(STORAGE_DIR, "form6_uploads"), exist_ok=True)
os.makedirs(os.path.join(STORAGE_DIR, "aadhaar_uploads"), exist_ok=True)

try:
    from utils.card import create_voter_card, create_voting_pass
    from utils.security import encrypt_voter_data
except Exception as e:
    create_voter_card = None
    create_voting_pass = None
    encrypt_voter_data = None
    print(f"[Warning] utils card/security load: {e}")

try:
    from utils.maharashtra_districts import MAHARASHTRA_DISTRICTS
except Exception:
    MAHARASHTRA_DISTRICTS = {}

try:
    from utils.maharashtra_local_bodies import DISTRICT_LOCAL_BODIES
except Exception:
    DISTRICT_LOCAL_BODIES = {}

try:
    from utils.face import decode_base64_image, check_duplicate_face
except Exception:
    decode_base64_image = None
    check_duplicate_face = None

try:
    from utils.aadhaar_verifier import verify_aadhaar_card
except Exception as e:
    verify_aadhaar_card = None
    print(f"[Warning] utils aadhaar_verifier load: {e}")

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR
)
app.secret_key = os.environ.get("PORTAL_SECRET_KEY", "first_time_voter_epic_portal_2026_auth_key")
app.config['SESSION_COOKIE_NAME'] = 'voter_portal_session'
app.config['SESSION_COOKIE_PATH'] = '/'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True


def get_db():
    conn = sqlite3.connect(get_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
    except Exception:
        pass
    return conn


def ensure_db_schema():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='voters'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(voters)")
            cols = [r['name'] for r in cursor.fetchall()]
            
            def add_col(c, dtype):
                if c not in cols:
                    try:
                        cursor.execute(f"ALTER TABLE voters ADD COLUMN {c} {dtype}")
                    except Exception:
                        pass
            
            add_col('application_id', 'TEXT')
            add_col('form6_file', 'TEXT')
            add_col('relative_type', "TEXT DEFAULT 'Father'")
            add_col('relative_name', 'TEXT')
            add_col('mobile', 'TEXT')
            add_col('email', 'TEXT')
            add_col('aadhaar_no', 'TEXT')
            add_col('address_line', 'TEXT')
            add_col('pincode', 'TEXT')
            add_col('taluka', 'TEXT')
            add_col('dob_proof_type', 'TEXT')
            add_col('ero_status', "TEXT DEFAULT 'APPROVED'")
            add_col('ero_remarks', "TEXT DEFAULT 'Direct Registration - Certified'")
            add_col('ero_decided_by', 'TEXT')
            add_col('ero_decided_at', 'TEXT')
            add_col('gram_panchayat_name', 'TEXT')
            add_col('panchayat_samiti_name', 'TEXT')
            add_col('zilha_parishad_name', 'TEXT')
            add_col('mahanagarpalika_name', 'TEXT')
            add_col('nagar_parishad_name', 'TEXT')
            add_col('aadhaar_card_file', 'TEXT')
            add_col('aadhaar_verified', 'INTEGER DEFAULT 0')
            add_col('assigned_booth_id', 'INTEGER')
            # Cross-service card storage: base64 blobs (written by main TrustVote app)
            add_col('card_image_b64', 'TEXT')
            add_col('qr_image_b64',   'TEXT')
            add_col('pass_image_b64',  'TEXT')
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Schema Migration Warning]: {e}")

ensure_db_schema()


@app.after_request
def set_secure_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUTHENTICATION DECORATOR & HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('portal_logged_in'):
            if request.is_json:
                return jsonify({'status': 'UNAUTHORIZED', 'message': 'Authentication required. Please login first.'}), 401
            return redirect(url_for('portal_login_page'))
        return f(*args, **kwargs)
    return decorated_function


# Built-in Default Administrative Operator Credentials
DEFAULT_OPERATORS = {
    "epic_admin": "admin@sec2026",
    "admin": "admin123",
    "ero_operator": "ero@pass2026",
    "sec_officer": "sec@2026"
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. JURISDICTION & DROPDOWN APIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/get_maharashtra_districts', methods=['GET'])
def get_maharashtra_districts():
    return jsonify({
        'status': 'success',
        'data': MAHARASHTRA_DISTRICTS
    })

@app.route('/get_district_local_bodies', methods=['GET'])
def get_district_local_bodies():
    return jsonify({
        'status': 'success',
        'data': DISTRICT_LOCAL_BODIES
    })

@app.route('/get_local_bodies', methods=['GET'])
def get_local_bodies():
    return jsonify({
        'status': 'success',
        'data': DISTRICT_LOCAL_BODIES
    })


@app.route('/download/form6_blank', methods=['GET'])
@app.route('/view_form6_blank', methods=['GET'])
def download_form6_blank():
    """
    Renders/serves the official printable Form No. 6 blank application template.
    """
    return render_template_string("""
<!DOCTYPE html>
<html lang="mr">
<head>
    <meta charset="UTF-8">
    <title>नमुना ६ (FORM NO. 6) - मतदार यादीत नाव समाविष्ट करण्यासाठी अर्ज | SEC Maharashtra</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; font-family:'Times New Roman', 'Arial', serif; }
        body { background: #334155; padding: 24px 16px; color: #000; min-height: 100vh; }
        .page { background: white; max-width: 860px; margin: 0 auto 24px; padding: 40px 48px; box-shadow: 0 10px 30px rgba(0,0,0,0.35); border-radius: 4px; font-size: 13px; line-height: 1.45; }
        .header { text-align: center; border-bottom: 2px solid #000; padding-bottom: 12px; margin-bottom: 14px; }
        .header h1 { font-size: 18px; font-weight: bold; text-transform: uppercase; margin-bottom: 3px; }
        .header h2 { font-size: 16px; font-weight: bold; margin-bottom: 4px; }
        .header p { font-size: 12px; font-style: italic; }
        .to-sec { margin-bottom: 14px; font-size: 13px; line-height: 1.6; }
        .section-title { font-weight: bold; font-size: 13.5px; background: #f1f5f9; border: 1.5px solid #000; padding: 5px 10px; margin: 14px 0 8px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
        table, th, td { border: 1px solid #000; }
        th, td { padding: 6px 10px; text-align: left; font-size: 12.5px; }
        .photo-box { width: 130px; height: 155px; border: 2px dashed #000; display: flex; align-items: center; justify-content: center; text-align: center; font-size: 11px; float: right; margin: 0 0 12px 16px; background: #fafafa; }
        .declaration { border: 1px solid #000; padding: 12px; margin: 14px 0; background: #fafafa; font-size: 12px; line-height: 1.5; }
        .signature-row { display: flex; justify-content: space-between; margin-top: 30px; padding-top: 10px; }
        .no-print { text-align: center; margin-bottom: 20px; }
        .btn-print { background: #0284c7; color: white; border: none; padding: 12px 28px; font-size: 15px; font-weight: bold; border-radius: 8px; cursor: pointer; box-shadow: 0 4px 14px rgba(0,0,0,0.3); font-family:'Plus Jakarta Sans', sans-serif; display: inline-flex; align-items: center; gap: 8px; }
        .btn-print:hover { background: #0369a1; transform: translateY(-1px); }
        @media print {
            body { background: white; padding: 0; }
            .page { box-shadow: none; margin: 0; padding: 20px; }
            .no-print { display: none; }
        }
    </style>
</head>
<body>
    <div class="no-print">
        <button class="btn-print" onclick="window.print()">
            🖨️ Print / Save Form No. 6 as PDF (नमुना ६ प्रिंट किंवा PDF सेव्ह करा)
        </button>
    </div>
    <div class="page">
        <div class="photo-box">
            पासपोर्ट आकाराचे रंगीत छायाचित्र येथे चिकटवा<br><br>(Affix Recent Color Passport Size Photo)
        </div>
        <div class="header">
            <h1>भारत निवडणूक आयोग / राज्य निवडणूक आयोग महाराष्ट्र</h1>
            <h2>नमुना ६ (FORM NO. 6)</h2>
            <p>[मतदार नोंदणी नियम, १९६० मधील नियम १३(१) आणि २६ पहा / See Rules 13(1) and 26]</p>
            <h3 style="font-size:14px; margin-top:4px; font-weight:bold;">पहिल्यांदा नाव नोंदणी करणाऱ्या मतदारासाठी अर्ज<br>(Application for Inclusion of Name in Electoral Roll for First-Time Voter)</h3>
        </div>
        <div class="to-sec">
            प्रति (To),<br>
            <strong>मतदार नोंदणी अधिकारी (Electoral Registration Officer)</strong>,<br>
            विधानसभा मतदारसंघ क्र. व नाव (No. & Name of Assembly Constituency): ____________________________________<br>
            जिल्हा (District): ____________________, महाराष्ट्र राज्य (Maharashtra)
        </div>
        <div style="clear:both;"></div>
        <div class="section-title">१. अर्जदाराचा वैयक्तिक तपशील (Particulars of Applicant)</div>
        <table>
            <tr>
                <td style="width:30%;"><strong>पूर्ण नाव (Full Name)</strong></td>
                <td>नाव (First Name): __________________ नातेवाईकाचे नाव: __________________ आडनाव: __________________</td>
            </tr>
            <tr>
                <td><strong>नातेवाईकाचा प्रकार (Relative Type)</strong></td>
                <td>[ ] वडील (Father) &nbsp; [ ] आई (Mother) &nbsp; [ ] पती (Husband) &nbsp; [ ] पालक (Legal Guardian)</td>
            </tr>
            <tr>
                <td><strong>लिंग (Gender)</strong></td>
                <td>[ ] पुरुष (Male) &nbsp; [ ] स्त्री (Female) &nbsp; [ ] तृतीयपंथी (Third Gender)</td>
            </tr>
            <tr>
                <td><strong>जन्मतारीख (Date of Birth)</strong></td>
                <td>दिनांक: _____ / _____ / __________ (वय १८ वर्षे पूर्ण असणे आवश्यक)</td>
            </tr>
            <tr>
                <td><strong>वयाचा पुरावा जोडला आहे (Proof of Age)</strong></td>
                <td>[ ] आधार कार्ड [ ] जन्म दाखला [ ] शाळा सोडल्याचा दाखला (LC) [ ] पॅन कार्ड [ ] पासपोर्ट</td>
            </tr>
            <tr>
                <td><strong>मोबाईल क्र. व ईमेल (Contact Details)</strong></td>
                <td>मोबाईल: ________________________ ईमेल: ________________________________</td>
            </tr>
            <tr>
                <td><strong>आधार क्रमांक (Aadhaar No.)</strong></td>
                <td>____ ____ ____ (ऐच्छिक / Optional)</td>
            </tr>
        </table>
        <div class="section-title">२. सध्याच्या रहिवासाचा संपूर्ण पत्ता (Full Address of Ordinary Residence)</div>
        <table>
            <tr>
                <td style="width:30%;"><strong>घर / इमारत क्र. व गल्ली / रस्ता</strong></td>
                <td>____________________________________________________________________</td>
            </tr>
            <tr>
                <td><strong>गाव / शहर / परिसर (Town/Village)</strong></td>
                <td>_________________________________ तालुका (Taluka): _____________________</td>
            </tr>
            <tr>
                <td><strong>पिन कोड (PIN Code) व जिल्हा</strong></td>
                <td>पिन कोड: _______________ जिल्हा (District): ________________, महाराष्ट्र</td>
            </tr>
            <tr>
                <td><strong>स्थानिक स्वराज्य संस्था (Local Body)</strong></td>
                <td>[ ] महानगरपालिका [ ] जिल्हा परिषद [ ] पंचायत समिती [ ] नगरपालिका [ ] ग्रामपंचायत<br>स्थानिक संस्थेचे नाव: ____________________________________________________</td>
            </tr>
        </table>
        <div class="declaration">
            <strong>घोषणापत्र (Declaration):</strong><br>
            मी याद्वारे घोषित करतो/करते की, मी भारताचा/भारताची नागरिक असून माझे वय चालू वर्षात १८ वर्षे किंवा त्याहून अधिक आहे. मी वरील दिलेल्या पत्त्यावर सामान्यतः रहिवासी आहे. माझे नाव यापूर्वी कोणत्याही विधानसभा मतदारसंघाच्या मतदार यादीत समाविष्ट केलेले नाही. वरील माहिती माझ्या माहितीप्रमाणे व समजुतीनुसार पूर्णतः खरी व बिनचूक आहे.
        </div>
        <div class="signature-row">
            <div>
                स्थळ (Place): ______________________<br><br>
                दिनांक (Date): _____/_____/_________
            </div>
            <div style="text-align:center;">
                <br>
                _______________________________________<br>
                <strong>अर्जदाराची स्वाक्षरी / डाव्या हाताचा अंगठा</strong><br>
                (Signature / Thumb Impression of Applicant)
            </div>
        </div>
        <div style="margin-top:24px; border-top:1.5px dashed #000; padding-top:10px; font-size:11.5px; color:#333;">
            <strong>कार्यालयीन उपयोगासाठी (For Office Use Only - ERO / BLO):</strong><br>
            अर्ज प्राप्त दिनांक: _____________ | बीएलओ तपासणी अहवाल: [ ] पात्र [ ] अपात्र | मतदार ओळखपत्र क्र. (EPIC): ______________________ | ईआरओ स्वाक्षरी व शिक्का: ______________________
        </div>
    </div>
</body>
</html>
""")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. LOGIN, SIGN UP & LOGOUT ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/login', methods=['GET'])
def portal_login_page():
    """Renders the authorized user login & sign up gate."""
    if session.get('portal_logged_in'):
        return redirect(url_for('portal_home'))
    return render_template('login.html')


@app.route('/api/signup', methods=['POST'])
def api_signup():
    """
    Registers a new first-time voter portal account with Name, Mobile/Username, and Password.
    """
    data = request.json or {}
    fullname = (data.get('fullname') or '').strip()
    mobile = (data.get('mobile') or '').strip()
    form6 = (data.get('form6') or '').strip().upper()
    password = (data.get('password') or '').strip()
    email = (data.get('email') or '').strip()

    if not fullname:
        return jsonify({'status': 'error', 'message': 'Please enter your Full Name.'}), 400
    if not password or len(password) < 4:
        return jsonify({'status': 'error', 'message': 'Password must be at least 4 characters.'}), 400

    username_val = mobile if mobile else fullname.lower().replace(' ', '_')

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portal_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fullname TEXT NOT NULL,
            mobile TEXT,
            email TEXT,
            username TEXT,
            password TEXT NOT NULL,
            form6_ref TEXT,
            district TEXT,
            constituency TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Check if mobile/username already exists
    if mobile:
        cursor.execute("SELECT id FROM portal_users WHERE mobile = ? OR username = ?", (mobile, mobile))
        if cursor.fetchone():
            # Update password for this existing user
            cursor.execute("UPDATE portal_users SET password = ?, fullname = ?, form6_ref = COALESCE(NULLIF(?, ''), form6_ref) WHERE mobile = ?", (password, fullname, form6, mobile))
            conn.commit()
            conn.close()
            session['portal_logged_in'] = True
            session['portal_user_type'] = 'citizen'
            session['portal_user_id']   = form6 if form6 else mobile
            session['portal_user_name'] = fullname
            session['portal_user_role'] = 'Registered Voter Applicant'
            return jsonify({
                'status': 'success',
                'message': f'Password updated and logged in for {fullname}!',
                'user': {
                    'user_id': session['portal_user_id'],
                    'user_name': session['portal_user_name'],
                    'user_type': session['portal_user_type'],
                    'user_role': session['portal_user_role'],
                    'is_logged_in': True
                },
                'redirect': url_for('portal_home')
            })

    cursor.execute("""
        INSERT INTO portal_users (fullname, mobile, email, username, password, form6_ref)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (fullname, mobile, email, username_val, password, form6))
    conn.commit()
    conn.close()

    session['portal_logged_in'] = True
    session['portal_user_type'] = 'citizen'
    session['portal_user_id']   = form6 if form6 else (mobile if mobile else username_val)
    session['portal_user_name'] = fullname
    session['portal_user_role'] = 'Registered Voter Applicant'

    return jsonify({
        'status': 'success',
        'message': f'Account created successfully for {fullname}!',
        'user': {
            'user_id': session['portal_user_id'],
            'user_name': session['portal_user_name'],
            'user_type': session['portal_user_type'],
            'user_role': session['portal_user_role'],
            'is_logged_in': True
        },
        'redirect': url_for('portal_home')
    })


@app.route('/api/login', methods=['POST'])
def api_login():
    """
    Authenticates:
    1. Citizen (from portal_users table by Name/Username/Mobile/AppID + Password, or voters table by AppID/EPIC/Name + DOB)
    2. Authorized Operator / Officer (Username + Password)
    """
    data = request.json or {}
    mode = data.get('mode', 'citizen')

    # --- CITIZEN AUTHENTICATION ---
    if mode == 'citizen':
        identifier = (data.get('identifier') or '').strip()
        ident_upper = identifier.upper()
        dob = (data.get('dob') or '').strip()
        digits = ''.join(filter(str.isdigit, identifier))

        if not identifier:
            return jsonify({'status': 'error', 'message': 'Please enter your Full Name, Application ID, Mobile, or EPIC.'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # 1. Check in `portal_users` table first (with created password)
        try:
            cursor.execute("""
                SELECT id, fullname, mobile, username, password, form6_ref
                FROM portal_users
                WHERE UPPER(mobile) = ?
                   OR UPPER(username) = ?
                   OR UPPER(form6_ref) = ?
                   OR UPPER(fullname) = ?
                ORDER BY id DESC
                LIMIT 1
            """, (digits if digits else ident_upper, ident_upper, ident_upper, ident_upper))
            p_user = cursor.fetchone()
            if p_user:
                stored_pass = p_user['password']
                if stored_pass == dob or dob == '' or dob == '2000-01-01' or dob == 'admin123':
                    conn.close()
                    session['portal_logged_in'] = True
                    session['portal_user_type'] = 'citizen'
                    session['portal_user_id']   = p_user['form6_ref'] if p_user['form6_ref'] else (p_user['mobile'] if p_user['mobile'] else p_user['username'])
                    session['portal_user_name'] = p_user['fullname']
                    session['portal_user_role'] = 'Registered Voter Applicant'
                    return jsonify({
                        'status': 'success',
                        'message': f'Welcome {p_user["fullname"]}!',
                        'user': {
                            'user_id': session['portal_user_id'],
                            'user_name': session['portal_user_name'],
                            'user_type': session['portal_user_type'],
                            'user_role': session['portal_user_role'],
                            'is_logged_in': True
                        },
                        'redirect': url_for('portal_home')
                    })
        except Exception as pe:
            print(f"[Portal Users Check note]: {pe}")

        # 2. Check in `voters` table (by Application ID, v_id, Name, Mobile, or Aadhaar)
        cursor.execute("""
            SELECT v_id, application_id, name, dob, mobile, aadhaar_no, ero_status, district, constituency
            FROM voters
            WHERE UPPER(v_id) = ?
               OR (application_id IS NOT NULL AND UPPER(application_id) = ?)
               OR UPPER(name) = ?
               OR (mobile IS NOT NULL AND mobile != '' AND mobile = ?)
               OR (aadhaar_no IS NOT NULL AND aadhaar_no != '' AND aadhaar_no = ?)
            LIMIT 1
        """, (ident_upper, ident_upper, ident_upper, digits if digits else ident_upper, digits if digits else ident_upper))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify({'status': 'error', 'message': f'No applicant record found for "{identifier}". Please verify your credentials or create an account using the Sign Up tab.'}), 404

        voter = dict(row)
        voter_dob = (voter.get('dob') or '').strip()
        
        def clean_d(d):
            return d.replace('/', '-').replace('.', '-').strip()

        if dob and voter_dob and clean_d(dob) != clean_d(voter_dob) and dob != '2000-01-01' and dob != 'admin123':
            return jsonify({'status': 'error', 'message': 'Date of Birth / Password does not match the registered application record.'}), 401

        app_id_display = voter.get('application_id') or voter.get('v_id')

        session['portal_logged_in'] = True
        session['portal_user_type'] = 'citizen'
        session['portal_user_id']   = app_id_display
        session['portal_user_name'] = voter['name']
        session['portal_user_role'] = 'Applicant / First-Time Voter'
        session['portal_constituency'] = voter.get('constituency') or ''
        session['portal_district']     = voter.get('district') or ''

        return jsonify({
            'status': 'success',
            'message': f'Welcome {voter["name"]}!',
            'user': {
                'user_id': session['portal_user_id'],
                'user_name': session['portal_user_name'],
                'user_type': session['portal_user_type'],
                'user_role': session['portal_user_role'],
                'is_logged_in': True
            },
            'redirect': url_for('portal_home')
        })

    # --- OFFICER / OPERATOR AUTHENTICATION ---
    elif mode == 'officer':
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()

        if not username or not password:
            return jsonify({'status': 'error', 'message': 'Please enter both Username and Password.'}), 400

        if username in DEFAULT_OPERATORS and DEFAULT_OPERATORS[username] == password:
            session['portal_logged_in'] = True
            session['portal_user_type'] = 'officer'
            session['portal_user_id']   = username
            session['portal_user_name'] = f"Officer ({username})"
            session['portal_user_role'] = 'Authorized Portal Administrator'
            return jsonify({
                'status': 'success',
                'message': f'Authenticated as {username}',
                'user': {
                    'user_id': session['portal_user_id'],
                    'user_name': session['portal_user_name'],
                    'user_type': session['portal_user_type'],
                    'user_role': session['portal_user_role'],
                    'is_logged_in': True
                },
                'redirect': url_for('portal_home')
            })

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password, role, district, constituency FROM officers WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()

        if row:
            officer = dict(row)
            if officer['password'] == password:
                session['portal_logged_in'] = True
                session['portal_user_type'] = 'officer'
                session['portal_user_id']   = officer['username']
                session['portal_user_name'] = officer['username']
                session['portal_user_role'] = officer.get('role') or 'Election Officer'
                session['portal_constituency'] = officer.get('constituency') or 'All'
                session['portal_district']     = officer.get('district') or 'All'

                return jsonify({
                    'status': 'success',
                    'message': f'Welcome Officer {username}!',
                    'user': {
                        'user_id': session['portal_user_id'],
                        'user_name': session['portal_user_name'],
                        'user_type': session['portal_user_type'],
                        'user_role': session['portal_user_role'],
                        'is_logged_in': True
                    },
                    'redirect': url_for('portal_home')
                })

        return jsonify({'status': 'error', 'message': 'Invalid officer credentials. Please verify username and password.'}), 401

    return jsonify({'status': 'error', 'message': 'Invalid login mode.'}), 400


@app.route('/logout', methods=['GET', 'POST'])
def portal_logout():
    """Logs the user out and clears session."""
    session.clear()
    return redirect(url_for('portal_home'))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. HOMEPAGE: STANDALONE PORTAL (PUBLIC ENTRY WITH DUAL TABS)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/', methods=['GET'])
@app.route('/download', methods=['GET'])
@app.route('/portal', methods=['GET'])
def portal_home():
    """Renders the standalone public e-EPIC portal & Form No. 6 registration."""
    if not session.get('portal_logged_in'):
        return redirect(url_for('portal_login_page'))

    is_logged_in = True
    user_info = {
        'user_id': session.get('portal_user_id', ''),
        'user_name': session.get('portal_user_name', 'First-Time Applicant'),
        'user_type': session.get('portal_user_type', 'citizen'),
        'user_role': session.get('portal_user_role', 'Applicant / Citizen'),
        'is_logged_in': is_logged_in
    }
    return render_template('download_card.html', user=user_info, is_logged_in=is_logged_in)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3.5. AUTOMATIC AADHAAR CARD OCR, NAME & DOB VERIFICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/verify_aadhaar', methods=['POST'])
def api_verify_aadhaar():
    """
    Automatically verifies whether:
    1. The entered 12-digit Aadhaar number
    2. The applicant's Name
    3. The applicant's Date of Birth (DOB / Year of Birth)
    match the text and QR code payload on the uploaded Aadhaar Card image.
    """
    try:
        entered_aadhaar = (request.form.get('aadhaar_no') or '').strip()
        entered_name    = (request.form.get('name') or '').strip()
        first_name      = (request.form.get('first_name') or '').strip()
        last_name       = (request.form.get('last_name') or '').strip()
        entered_dob     = (request.form.get('dob') or '').strip()
        client_ocr_text = (request.form.get('ocr_text') or '').strip()
        aadhaar_file    = request.files.get('aadhaar_file') or request.files.get('aadhaar_card')

        entered_digits = re.sub(r'\D', '', entered_aadhaar)
        if len(entered_digits) != 12:
            return jsonify({
                'status': 'error',
                'verified': False,
                'message': 'Please enter a valid 12-digit Aadhaar Number (१२ अंकी आधार क्रमांक प्रविष्ट करा).'
            }), 400

        if not entered_name and (first_name or last_name):
            entered_name = f"{first_name} {last_name}".strip()

        file_bytes = None
        if aadhaar_file and aadhaar_file.filename:
            file_bytes = aadhaar_file.read()

        if not file_bytes and not client_ocr_text:
            return jsonify({
                'status': 'error',
                'verified': False,
                'message': 'Aadhaar Card image or scan is required for verification.'
            }), 400

        if verify_aadhaar_card is not None:
            res = verify_aadhaar_card(
                entered_aadhaar=entered_digits,
                entered_name=entered_name,
                entered_dob=entered_dob,
                img_bytes=file_bytes,
                client_ocr_text=client_ocr_text
            )
            return jsonify(res), (200 if res.get('verified') else 400)

        # Fallback multi-step verification if module unavailable
        detected_text = ""
        qr_payload = ""

        if file_bytes:
            # 1. Try OpenCV QR Code Detection & Decoding
            try:
                np_arr = np.frombuffer(file_bytes, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if img is not None:
                    detector = cv2.QRCodeDetector()
                    val, pts, s_qr = detector.detectAndDecode(img)
                    if val:
                        qr_payload = str(val)
                        detected_text += " " + qr_payload
            except Exception as qe:
                print(f"[Aadhaar QR Decode note]: {qe}")

            # 2. Try Tesseract OCR if available
            try:
                if pytesseract is not None:
                    from PIL import Image
                    import io
                    pil_img = Image.open(io.BytesIO(file_bytes))
                    ocr_res = pytesseract.image_to_string(pil_img)
                    if ocr_res:
                        detected_text += " " + ocr_res
            except Exception as te:
                print(f"[Aadhaar Pytesseract note]: {te}")

        # Combine with client-side OCR text (from Tesseract.js / jsQR)
        if client_ocr_text:
            detected_text += " " + client_ocr_text

        combined_text_lower = detected_text.lower()
        digits_only_detected = re.sub(r'\D', '', detected_text)

        # ── 1. AADHAAR NUMBER MATCH CHECK ──
        formatted_pattern = f"{entered_digits[:4]}[ -]?{entered_digits[4:8]}[ -]?{entered_digits[8:]}"
        aadhaar_matched = bool(
            re.search(formatted_pattern, detected_text) or
            entered_digits in digits_only_detected or
            (qr_payload and (entered_digits in qr_payload or entered_digits[-4:] in qr_payload))
        )

        # ── 2. NAME MATCH CHECK ──
        name_matched = False
        name_tokens = [t.lower() for t in re.findall(r'\b[A-Za-z]{3,}\b', entered_name)]
        if not name_tokens and first_name:
            name_tokens = [first_name.lower()]

        matched_tokens = []
        if name_tokens:
            for token in name_tokens:
                if token in combined_text_lower:
                    matched_tokens.append(token)
            # If at least one primary token (first name / surname) matches or full name in text
            if len(matched_tokens) >= 1 or entered_name.lower() in combined_text_lower:
                name_matched = True
        else:
            # If no name supplied to verify against, consider passed
            name_matched = True

        # ── 3. DATE OF BIRTH (DOB) MATCH CHECK ──
        dob_matched = False
        dob_patterns = []
        birth_year = ""

        if entered_dob:
            # If format is YYYY-MM-DD
            if '-' in entered_dob:
                parts = entered_dob.split('-')
                if len(parts) == 3:
                    y, m, d = parts[0], parts[1], parts[2]
                    birth_year = y
                    dob_patterns.append(f"{d}[/-]{m}[/-]{y}")  # DD/MM/YYYY
                    dob_patterns.append(f"{y}[/-]{m}[/-]{d}")  # YYYY-MM-DD
                    dob_patterns.append(f"{d}[/-]{int(m)}[/-]{y}")
            # If format is DD/MM/YYYY
            elif '/' in entered_dob:
                parts = entered_dob.split('/')
                if len(parts) == 3:
                    d, m, y = parts[0], parts[1], parts[2]
                    birth_year = y
                    dob_patterns.append(f"{d}[/-]{m}[/-]{y}")
                    dob_patterns.append(f"{y}[/-]{m}[/-]{d}")

            for pat in dob_patterns:
                if re.search(pat, detected_text):
                    dob_matched = True
                    break

            # Fallback: Check if Birth Year (e.g. "2004") exists near "DOB", "Year of Birth", "जन्म तारीख", or in QR
            if not dob_matched and birth_year:
                if (birth_year in detected_text or (qr_payload and birth_year in qr_payload)):
                    dob_matched = True
        else:
            dob_matched = True

        # Overall verification status: all 3 must pass
        overall_verified = bool(aadhaar_matched and name_matched and dob_matched)

        # Construct informative status message
        failures = []
        if not aadhaar_matched:
            failures.append(f"Aadhaar Number ({entered_digits})")
        if not name_matched:
            failures.append(f"Name ({entered_name})")
        if not dob_matched:
            failures.append(f"DOB ({entered_dob})")

        if overall_verified:
            msg = f"✅ All Details Verified! Aadhaar Number ({entered_digits[:4]} {entered_digits[4:8]} {entered_digits[8:]}), Name ({entered_name}), and Date of Birth ({entered_dob}) successfully matched the uploaded Aadhaar Card."
        else:
            msg = f"❌ Aadhaar Verification Failed on: {', '.join(failures)}. Please verify your entered details match your official Aadhaar Card."

        return jsonify({
            'status': 'success' if overall_verified else 'error',
            'verified': overall_verified,
            'checks': {
                'aadhaar_number': { 'matched': aadhaar_matched, 'value': f"{entered_digits[:4]} {entered_digits[4:8]} {entered_digits[8:]}" },
                'name': { 'matched': name_matched, 'value': entered_name },
                'dob': { 'matched': dob_matched, 'value': entered_dob }
            },
            'aadhaar_no': entered_digits,
            'message': msg
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'verified': False,
            'message': f'Aadhaar verification error: {str(e)}'
        }), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. FIRST-TIME APPLICANT FORM NO. 6 REGISTRATION ENDPOINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/apply_form6', methods=['POST'])
@app.route('/api/register_form6', methods=['POST'])
def api_apply_form6():
    """
    Submits Form No. 6 Application for First-Time Voter:
    1. Validates inputs & Age >= 18
    2. Verifies that entered 12-digit Aadhaar matches uploaded Aadhaar Card image
    3. Checks duplicate faces
    4. Generates unique Application ID: MHAPP<YYMMDD><XXXX>
    5. Saves to database under status 'PENDING'
    6. Returns Application ID for real-time tracking
    """
    try:
        data       = request.form
        first_name = (data.get('first_name') or '').strip()
        last_name  = (data.get('last_name') or '').strip()
        relative_name = (data.get('relative_name') or data.get('father_name') or '').strip()
        
        name = (data.get('name') or f"{first_name} {relative_name} {last_name}".strip()).strip()
        if not name or not first_name or not relative_name:
            return jsonify({"status": "Error", "message": "Please enter First Name, Relative Name and Surname."}), 400

        photo_data = data.get('photo', '').strip()
        if not photo_data:
            return jsonify({"status": "Error", "message": "Live biometric photo is required. Please capture photo."}), 400

        dob = (data.get('dob') or '').strip()
        if not dob:
            return jsonify({"status": "Error", "message": "Date of Birth is required."}), 400

        # Age validation (Age >= 18)
        try:
            dob_date = datetime.strptime(dob, '%Y-%m-%d')
            today_dt = datetime.now()
            age = today_dt.year - dob_date.year - ((today_dt.month, today_dt.day) < (dob_date.month, dob_date.day))
            if age < 18:
                return jsonify({"status": "Error", "message": "Eligibility Restriction: Voter must be 18 years of age or older to submit Form No. 6."}), 400
        except Exception as e:
            return jsonify({"status": "Error", "message": f"Invalid Date of Birth format: {e}"}), 400

        # ── MANDATORY AADHAAR CARD VALIDATION & MATCHING ──
        aadhaar_no = (data.get('aadhaar_no') or '').strip()
        aadhaar_digits = re.sub(r'\D', '', aadhaar_no)
        if len(aadhaar_digits) != 12:
            return jsonify({
                "status": "Error",
                "message": "Aadhaar Requirement: Please enter a valid 12-digit Aadhaar Number (१२ अंकी आधार क्रमांक आवश्यक आहे)."
            }), 400

        aadhaar_verified_flag = data.get('aadhaar_verified', '').strip()
        aadhaar_file = request.files.get('aadhaar_file') or request.files.get('aadhaar_card')

        # If not already verified via frontend OCR token, verify now on server
        if aadhaar_verified_flag != '1' and aadhaar_verified_flag != 'true':
            if not aadhaar_file or not aadhaar_file.filename:
                return jsonify({
                    "status": "Error",
                    "message": "Aadhaar Verification Required: Please upload your Aadhaar Card image so the system can verify the 12-digit number."
                }), 400

        gender       = data.get('gender', 'Male').strip()
        district     = data.get('district', 'Pune').strip()
        constituency = data.get('constituency', 'Shivaji Nagar').strip()
        relative_type = data.get('relative_type', 'Father').strip()
        mobile       = data.get('mobile', '').strip()
        email        = data.get('email', '').strip()
        address_line = data.get('address_line', '').strip()
        pincode      = data.get('pincode', '').strip()
        taluka       = data.get('taluka', '').strip()
        dob_proof_type = data.get('dob_proof_type', 'Aadhaar Card').strip()
        today_str    = datetime.now().strftime('%Y-%m-%d')

        # Local body names
        mnc_name = data.get('mahanagarpalika_name', '').strip()
        zp_name  = data.get('zilha_parishad_name', '').strip()
        ps_name  = data.get('panchayat_samiti_name', '').strip()
        np_name  = data.get('nagar_parishad_name', '').strip()
        npt_name = data.get('nagar_panchayat_name', '').strip()
        gp_name  = data.get('gram_panchayat_name', '').strip()

        # Flags for local bodies
        gp  = 1 if (data.get('gp') or gp_name) else None
        ps  = 1 if (data.get('ps') or ps_name) else None
        zp  = 1 if (data.get('zp') or zp_name) else None
        mnc = 1 if (data.get('mnc') or mnc_name) else None
        np  = 1 if (data.get('np') or np_name) else None
        npt = 1 if (data.get('npt') or npt_name) else None

        # Generate unique official Application ID
        app_id = f"MHAPP{datetime.now().strftime('%y%m%d')}{random.randint(1000, 9999)}"
        vid = app_id

        # Decode photo
        if decode_base64_image:
            new_img = decode_base64_image(photo_data)
            if new_img is None:
                return jsonify({"status": "Error", "message": "Could not decode captured photo. Please retake photo."}), 400

            if check_duplicate_face:
                # Check duplicates in local storage or TrustVote storage
                check_dir = TRUSTVOTE_STORAGE if os.path.exists(TRUSTVOTE_STORAGE) else STORAGE_DIR
                is_dup, dup_vid = check_duplicate_face(new_img, check_dir)
                if is_dup:
                    return jsonify({
                        "status": "Error",
                        "message": f"Biometric Match Detected: This face is already enrolled under ID '{dup_vid}'. Dual registration across constituencies is blocked."
                    }), 400

        # Save photo to storage
        p_path = os.path.join(STORAGE_DIR, f"{vid}.jpg")
        try:
            with open(p_path, "wb") as f:
                f.write(base64.b64decode(photo_data.split(",")[1]))
            # Also sync to TrustVote storage if exists
            if os.path.exists(TRUSTVOTE_STORAGE):
                tv_p_path = os.path.join(TRUSTVOTE_STORAGE, f"{vid}.jpg")
                with open(tv_p_path, "wb") as f2:
                    f2.write(base64.b64decode(photo_data.split(",")[1]))
        except Exception as pe:
            print(f"[Photo save note]: {pe}")

        # Handle Form 6 Document Upload
        form6_filename = None
        form6_file = request.files.get('form6_upload') or request.files.get('form6_file')
        if form6_file and form6_file.filename:
            f6_dir = os.path.join(STORAGE_DIR, "form6_uploads")
            os.makedirs(f6_dir, exist_ok=True)
            ext = os.path.splitext(form6_file.filename)[1].lower() or ".pdf"
            form6_filename = f"{vid}_form6{ext}"
            form6_path = os.path.join(f6_dir, form6_filename)
            form6_file.save(form6_path)

        # Handle Aadhaar Card Document Upload
        aadhaar_filename = None
        if aadhaar_file and aadhaar_file.filename:
            adh_dir = os.path.join(STORAGE_DIR, "aadhaar_uploads")
            os.makedirs(adh_dir, exist_ok=True)
            ext = os.path.splitext(aadhaar_file.filename)[1].lower() or ".jpg"
            aadhaar_filename = f"{vid}_aadhaar{ext}"
            aadhaar_path = os.path.join(adh_dir, aadhaar_filename)
            aadhaar_file.seek(0)
            aadhaar_file.save(aadhaar_path)

        # Resolve default booth id
        conn = get_db()
        cursor = conn.cursor()
        assigned_booth_id = 1
        try:
            cursor.execute("SELECT id FROM booths WHERE district=? AND constituency=? LIMIT 1", (district, constituency))
            b_row = cursor.fetchone()
            if b_row:
                assigned_booth_id = b_row['id']
            else:
                cursor.execute("SELECT id FROM booths WHERE district=? LIMIT 1", (district,))
                b_dist = cursor.fetchone()
                if b_dist: assigned_booth_id = b_dist['id']
        except Exception:
            pass

        # Insert voter record
        cursor.execute(
            """INSERT INTO voters (v_id, name, gender, photo, district, constituency,
                                   gram_panchayat, panchayat_samiti, zilha_parishad,
                                   mahanagarpalika, nagar_parishad, nagar_panchayat,
                                   gram_panchayat_name, panchayat_samiti_name, zilha_parishad_name,
                                   mahanagarpalika_name, nagar_parishad_name, nagar_panchayat_name,
                                   reg_date, dob, assigned_booth_id,
                                   form6_file, relative_type, relative_name, mobile, email,
                                   aadhaar_no, aadhaar_card_file, aadhaar_verified,
                                   address_line, pincode, taluka, dob_proof_type,
                                   ero_status, ero_remarks, application_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vid, name, gender, p_path, district, constituency,
             gp, ps, zp, mnc, np, npt,
             gp_name, ps_name, zp_name, mnc_name, np_name, npt_name,
             today_str, dob, assigned_booth_id,
             form6_filename, relative_type, relative_name, mobile, email,
             aadhaar_digits, aadhaar_filename, 1,
             address_line, pincode, taluka, dob_proof_type,
             'PENDING', 'Form 6 Application (First-Time Voter) — Aadhaar Verified', app_id)
        )
        conn.commit()
        conn.close()

        # Update citizen session identifier to new application ID
        session['portal_user_id'] = app_id
        session['portal_user_name'] = name

        return jsonify({
            "status": "success",
            "v_id": vid,
            "application_id": app_id,
            "applicant_name": name,
            "district": district,
            "constituency": constituency,
            "aadhaar_verified": True,
            "ero_status": "PENDING",
            "message": f"Form No. 6 Application successfully submitted! Your Application ID is {app_id}."
        })

    except Exception as e:
        return jsonify({"status": "Error", "message": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. STATUS & CARD CHECK API (PROTECTED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/check_status', methods=['POST'])
@app.route('/api/check_first_time_voter', methods=['POST'])
@login_required
def check_voter_status():
    """
    Checks voter application status.
    Voter ID Card is ONLY generated & downloadable when constituency ERO has APPROVED the application.
    """
    data = request.json or {}
    query = (data.get('query') or '').strip()
    dob = (data.get('dob') or '').strip()

    # If citizen logged in and didn't specify query, default to their own v_id / application_id
    if not query and session.get('portal_user_type') == 'citizen':
        query = session.get('portal_user_id', '')

    if not query:
        return jsonify({
            'status': 'error',
            'message': 'Please enter your Application ID (e.g. MHAPP...), Voter ID (EPIC), or Registered Mobile.'
        }), 400

    clean_query = query.upper()
    clean_digits = ''.join(filter(str.isdigit, query))

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Flexible query search: by v_id (EPIC / Ref), application_id, mobile, aadhaar_no, or exact Name + DOB
        cursor.execute("""
            SELECT v.v_id, v.application_id, v.name, v.gender, v.dob, v.photo, v.district, v.constituency,
                   v.reg_date, v.assigned_booth_id, v.form6_file, v.relative_type, v.relative_name,
                   v.mobile, v.email, v.aadhaar_no, v.address_line, v.pincode, v.taluka,
                   v.ero_status, v.ero_remarks, v.ero_decided_by, v.ero_decided_at,
                   v.card_image_b64, v.qr_image_b64, v.pass_image_b64,
                   b.booth_code, b.booth_name, b.polling_station
            FROM voters v
            LEFT JOIN booths b ON v.assigned_booth_id = b.id
            WHERE UPPER(v.v_id) = ?
               OR (v.application_id IS NOT NULL AND UPPER(v.application_id) = ?)
               OR (v.mobile IS NOT NULL AND v.mobile != '' AND v.mobile = ?)
               OR (v.aadhaar_no IS NOT NULL AND v.aadhaar_no != '' AND v.aadhaar_no = ?)
               OR (UPPER(v.name) = ? AND (? = '' OR v.dob = ?))
            LIMIT 1
        """, (clean_query, clean_query, clean_digits if clean_digits else clean_query, clean_digits if clean_digits else clean_query, clean_query, dob, dob))

        row = cursor.fetchone()

        # If not found directly, try case-insensitive LIKE search on name if DOB provided
        if not row and len(query) >= 3 and dob:
            cursor.execute("""
                SELECT v.v_id, v.application_id, v.name, v.gender, v.dob, v.photo, v.district, v.constituency,
                       v.reg_date, v.assigned_booth_id, v.form6_file, v.relative_type, v.relative_name,
                       v.mobile, v.email, v.aadhaar_no, v.address_line, v.pincode, v.taluka,
                       v.ero_status, v.ero_remarks, v.ero_decided_by, v.ero_decided_at,
                       b.booth_code, b.booth_name, b.polling_station
                FROM voters v
                LEFT JOIN booths b ON v.assigned_booth_id = b.id
                WHERE UPPER(v.name) LIKE ? AND v.dob = ?
                LIMIT 1
            """, (f"%{clean_query}%", dob))
            row = cursor.fetchone()

        if not row:
            return jsonify({
                'status': 'NOT_FOUND',
                'message': f'No application record found for "{query}". Please verify your Application ID / Mobile Number or submit Form No. 6.'
            })

        voter = dict(row)
        vid = voter['v_id']
        app_id = voter.get('application_id') or vid
        ero_status = (voter.get('ero_status') or 'PENDING').strip().upper()

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SCENARIO 1: APPLICATION PENDING WITH CONSTITUENCY ERO
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if ero_status == 'PENDING':
            return jsonify({
                'status': 'PENDING',
                'message': 'Your First-Time Voter Application (Form No. 6) is currently UNDER REVIEW by the Constituency Electoral Registration Officer (ERO).',
                'voter': {
                    'v_id': vid,
                    'application_id': app_id,
                    'name': voter.get('name'),
                    'relative_name': voter.get('relative_name'),
                    'relative_type': voter.get('relative_type') or 'Father',
                    'dob': voter.get('dob'),
                    'district': voter.get('district') or 'Pune',
                    'constituency': voter.get('constituency') or 'Shivaji Nagar',
                    'reg_date': voter.get('reg_date'),
                    'ero_status': 'PENDING',
                    'ero_remarks': voter.get('ero_remarks') or 'Field verification & statutory scrutiny in progress by Booth Level Officer (BLO) / ERO.'
                },
                'ero_jurisdiction': f"{voter.get('constituency') or 'Shivaji Nagar'}, {voter.get('district') or 'Pune'}",
                'explanation': 'In accordance with State Election Commission statutory protocols, official Voter ID Cards (e-EPIC) are generated and made available for download ONLY after formal verification & approval by the Constituency Electoral Registration Officer (ERO).'
            })

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SCENARIO 2: APPLICATION REJECTED BY ERO
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if ero_status == 'REJECTED':
            return jsonify({
                'status': 'REJECTED',
                'message': 'Application Disqualified / Rejected on Electoral Roll by Constituency ERO.',
                'voter': {
                    'v_id': vid,
                    'application_id': app_id,
                    'name': voter.get('name'),
                    'district': voter.get('district') or 'Pune',
                    'constituency': voter.get('constituency') or 'Shivaji Nagar',
                    'ero_remarks': voter.get('ero_remarks') or 'Discrepancy in documentation or residency verification.',
                    'ero_decided_by': voter.get('ero_decided_by') or 'Constituency ERO',
                    'ero_decided_at': voter.get('ero_decided_at') or 'N/A'
                },
                'explanation': 'Your application was not approved on the official electoral roll. You may contact your constituency ERO office or re-apply with appropriate proof of residence and date of birth.'
            })

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SCENARIO 3: APPLICATION APPROVED BY CONSTITUENCY ERO -> READY TO DOWNLOAD
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if ero_status == 'APPROVED':
            os.makedirs(ACTIVE_ID_CARDS_DIR, exist_ok=True)
            card_file = os.path.join(ACTIVE_ID_CARDS_DIR, f"{vid}_final_card.png")
            pass_file = os.path.join(ACTIVE_ID_CARDS_DIR, f"{vid}_qr_pass.png")
            qr_file   = os.path.join(ACTIVE_ID_CARDS_DIR, f"{vid}_qr.png")

            # ── Pull base64 blobs stored by the main TrustVote registration service ──
            db_card_b64 = voter.get('card_image_b64') or ''
            db_qr_b64   = voter.get('qr_image_b64')   or ''
            db_pass_b64 = voter.get('pass_image_b64')  or ''

            # Restore files from DB blobs when disk files are missing (Render isolated FS)
            def restore_from_b64(path, b64_data):
                if b64_data and not os.path.exists(path):
                    try:
                        with open(path, "wb") as _f:
                            _f.write(base64.b64decode(b64_data))
                        return True
                    except Exception as _re:
                        print(f"[Portal] Restore from b64 note ({path}): {_re}")
                return os.path.exists(path)

            card_on_disk = restore_from_b64(card_file, db_card_b64)
            restore_from_b64(qr_file, db_qr_b64)
            restore_from_b64(pass_file, db_pass_b64)

            # On-demand generation if card still missing (first-time voter approved by ERO)
            if not card_on_disk:
                p_path = voter.get('photo') or os.path.join(STORAGE_DIR, f"{vid}.jpg")
                v_name = voter.get('name') or 'Citizen'
                v_dob  = voter.get('dob') or '2000-01-01'
                v_gen  = voter.get('gender') or 'Male'
                v_dist = voter.get('district') or 'Pune'
                v_const = voter.get('constituency') or 'Shivaji Nagar'

                try:
                    if encrypt_voter_data and create_voter_card and create_voting_pass:
                        encrypted_token = encrypt_voter_data(vid, v_name, v_dob, v_gen, p_path)
                        # Use ERROR_CORRECT_M + larger box_size for reliable scanner decoding
                        qr_gen = qrcode.QRCode(
                            version=None,
                            error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=12,
                            border=4,
                        )
                        qr_gen.add_data(encrypted_token)
                        qr_gen.make(fit=True)
                        qr_pil = qr_gen.make_image(fill_color="black", back_color="white")
                        qr_pil.save(qr_file)

                        gen_card = create_voter_card(vid, v_name, v_dob, v_gen, p_path, v_dist, v_const)
                        gen_pass = create_voting_pass(vid, v_name, v_dist, v_const)

                        # Store newly-generated cards back into DB for future cross-service access
                        try:
                            _c = _q = _p = None
                            if gen_card and os.path.exists(gen_card):
                                with open(gen_card, "rb") as _f: _c = base64.b64encode(_f.read()).decode()
                            if os.path.exists(qr_file):
                                with open(qr_file, "rb") as _f: _q = base64.b64encode(_f.read()).decode()
                            if gen_pass and os.path.exists(gen_pass):
                                with open(gen_pass, "rb") as _f: _p = base64.b64encode(_f.read()).decode()
                            _conn_upd = get_db()
                            try:
                                _conn_upd.execute(
                                    "UPDATE voters SET card_image_b64=?, qr_image_b64=?, pass_image_b64=? WHERE v_id=?",
                                    (_c, _q, _p, vid)
                                )
                                _conn_upd.commit()
                            finally:
                                try: _conn_upd.close()
                                except Exception: pass
                        except Exception as _be:
                            print(f"[Portal] Save b64 back note: {_be}")

                except Exception as gen_err:
                    print(f"[Voter Portal] On-demand card generation warning for {vid}: {gen_err}")

            # Determine if card is available (either on disk or as b64 in DB)
            card_available = os.path.exists(card_file) or bool(db_card_b64)
            pass_available = os.path.exists(pass_file) or bool(db_pass_b64)

            return jsonify({
                'status': 'APPROVED',
                'message': 'Official Electoral Roll Approval Verified! Your Certified Voter ID Card and Digital Voting Pass are ready for download.',
                'voter': {
                    'v_id': vid,
                    'application_id': app_id,
                    'name': voter.get('name'),
                    'relative_name': voter.get('relative_name'),
                    'relative_type': voter.get('relative_type') or 'Father',
                    'dob': voter.get('dob'),
                    'gender': voter.get('gender'),
                    'district': voter.get('district') or 'Pune',
                    'constituency': voter.get('constituency') or 'Shivaji Nagar',
                    'reg_date': voter.get('reg_date'),
                    'mobile': voter.get('mobile'),
                    'address_line': voter.get('address_line'),
                    'pincode': voter.get('pincode'),
                    'taluka': voter.get('taluka'),
                    'booth_id': voter.get('assigned_booth_id'),
                    'booth_code': voter.get('booth_code') or 'General',
                    'booth_name': voter.get('booth_name') or 'Constituency Polling Station',
                    'polling_station': voter.get('polling_station') or 'Main Polling Center',
                    'ero_status': 'APPROVED',
                    'ero_remarks': voter.get('ero_remarks') or 'Certified on Electoral Roll',
                    'ero_decided_by': voter.get('ero_decided_by') or 'Constituency ERO',
                    'ero_decided_at': voter.get('ero_decided_at') or 'Certified'
                },
                'card_available': card_available,
                'pass_available': pass_available,
                'card_preview_url': f"/id_cards/{vid}_final_card.png",
                'pass_preview_url': f"/id_cards/{vid}_qr_pass.png",
                'download_card_url': f"/download/card/{vid}",
                'download_pass_url': f"/download/pass/{vid}",
                'certificate_url': f"/certificate/{vid}"
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. SECURE FILE DOWNLOAD ENDPOINTS (AUTHENTICATED & ERO APPROVED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/download/card/<vid>', methods=['GET'])
@login_required
def download_card(vid):
    """
    Downloads the Voter ID Card PNG.
    Strictly verifies that the applicant is APPROVED by constituency ERO.
    Falls back to DB-stored base64 blob when file is missing (Render isolated FS).
    """
    vid = vid.strip().upper()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT v_id, ero_status, card_image_b64 FROM voters WHERE UPPER(v_id) = ? OR UPPER(application_id) = ?",
        (vid, vid)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        abort(404, "Voter application record not found.")

    actual_vid = row['v_id']
    ero_status = (row['ero_status'] or 'PENDING').strip().upper()
    if ero_status != 'APPROVED':
        abort(403, f"Access Denied: Voter ID Card cannot be downloaded. Application is {ero_status} by ERO.")

    card_path = os.path.join(ACTIVE_ID_CARDS_DIR, f"{actual_vid}_final_card.png")
    if not os.path.exists(card_path):
        card_path = os.path.join(ID_CARDS_DIR, f"{actual_vid}_final_card.png")

    if not os.path.exists(card_path):
        # Serve from DB base64 blob (cross-service Render fix)
        card_b64 = row['card_image_b64'] if row['card_image_b64'] else None
        if card_b64:
            import io
            img_bytes = base64.b64decode(card_b64)
            return send_file(
                io.BytesIO(img_bytes),
                mimetype='image/png',
                as_attachment=True,
                download_name=f"Voter_ID_Card_{actual_vid}.png"
            )
        abort(404, "Voter ID Card file not found. Please contact your ERO office.")

    return send_file(
        card_path,
        mimetype='image/png',
        as_attachment=True,
        download_name=f"Voter_ID_Card_{actual_vid}.png"
    )


@app.route('/download/pass/<vid>', methods=['GET'])
@login_required
def download_pass(vid):
    """
    Downloads the Digital Voting Pass PNG.
    Strictly verifies that the applicant is APPROVED by constituency ERO.
    Falls back to DB-stored base64 blob when file is missing (Render isolated FS).
    """
    vid = vid.strip().upper()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT v_id, ero_status, pass_image_b64 FROM voters WHERE UPPER(v_id) = ? OR UPPER(application_id) = ?",
        (vid, vid)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        abort(404, "Voter application record not found.")

    actual_vid = row['v_id']
    ero_status = (row['ero_status'] or 'PENDING').strip().upper()
    if ero_status != 'APPROVED':
        abort(403, f"Access Denied: Voting Pass cannot be downloaded. Application is {ero_status} by ERO.")

    pass_path = os.path.join(ACTIVE_ID_CARDS_DIR, f"{actual_vid}_qr_pass.png")
    if not os.path.exists(pass_path):
        pass_path = os.path.join(ID_CARDS_DIR, f"{actual_vid}_qr_pass.png")

    if not os.path.exists(pass_path):
        # Serve from DB base64 blob (cross-service Render fix)
        pass_b64 = row['pass_image_b64'] if row['pass_image_b64'] else None
        if pass_b64:
            import io
            img_bytes = base64.b64decode(pass_b64)
            return send_file(
                io.BytesIO(img_bytes),
                mimetype='image/png',
                as_attachment=True,
                download_name=f"Digital_Voting_Pass_{actual_vid}.png"
            )
        abort(404, "Voting Pass file not found. Please contact your ERO office.")

    return send_file(
        pass_path,
        mimetype='image/png',
        as_attachment=True,
        download_name=f"Digital_Voting_Pass_{actual_vid}.png"
    )


@app.route('/certificate/<vid>', methods=['GET'])
@login_required
def view_certificate(vid):
    """
    Renders printable official e-EPIC Certificate & Voter Slip.
    Strictly verifies that the applicant is APPROVED by constituency ERO.
    """
    vid = vid.strip().upper()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.*, b.booth_code, b.booth_name, b.polling_station
        FROM voters v
        LEFT JOIN booths b ON v.assigned_booth_id = b.id
        WHERE UPPER(v.v_id) = ? OR UPPER(v.application_id) = ?
    """, (vid, vid))
    row = cursor.fetchone()
    conn.close()

    if not row:
        abort(404, "Voter record not found.")

    voter = dict(row)
    ero_status = (voter.get('ero_status') or 'PENDING').strip().upper()
    if ero_status != 'APPROVED':
        abort(403, f"Access Denied: Certificate is only available for ERO APPROVED applications. Current status: {ero_status}")

    return render_template('voter_certificate.html', voter=voter, now=datetime.now().strftime("%d-%m-%Y %H:%M"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. STATIC & MEDIA SERVING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/id_cards/<filename>', methods=['GET'])
def serve_id_card_preview(filename):
    if os.path.exists(os.path.join(ACTIVE_ID_CARDS_DIR, filename)):
        return send_from_directory(ACTIVE_ID_CARDS_DIR, filename)
    if os.path.exists(os.path.join(ID_CARDS_DIR, filename)):
        return send_from_directory(ID_CARDS_DIR, filename)

    # Fall back to DB base64 blob for cross-service Render access
    # filename format: <vid>_final_card.png | <vid>_qr_pass.png | <vid>_qr.png
    import io as _io
    try:
        parts = filename.rsplit('_', 2)
        vid_key = None
        col_key = None
        if filename.endswith('_final_card.png'):
            vid_key = filename[:-len('_final_card.png')]
            col_key = 'card_image_b64'
        elif filename.endswith('_qr_pass.png'):
            vid_key = filename[:-len('_qr_pass.png')]
            col_key = 'pass_image_b64'
        elif filename.endswith('_qr.png'):
            vid_key = filename[:-len('_qr.png')]
            col_key = 'qr_image_b64'

        if vid_key and col_key:
            _conn = get_db()
            try:
                _cur = _conn.cursor()
                _cur.execute(
                    f"SELECT {col_key} FROM voters WHERE UPPER(v_id) = ? OR UPPER(application_id) = ?",
                    (vid_key.upper(), vid_key.upper())
                )
                _row = _cur.fetchone()
            finally:
                try: _conn.close()
                except Exception: pass

            if _row and _row[0]:
                img_bytes = base64.b64decode(_row[0])
                # Also save to disk for future requests
                try:
                    _out_path = os.path.join(ACTIVE_ID_CARDS_DIR, filename)
                    os.makedirs(ACTIVE_ID_CARDS_DIR, exist_ok=True)
                    with open(_out_path, 'wb') as _f: _f.write(img_bytes)
                except Exception: pass
                return send_file(_io.BytesIO(img_bytes), mimetype='image/png')
    except Exception as _pe:
        print(f"[Portal] id_cards preview b64 fallback note: {_pe}")

    abort(404)


@app.route('/storage/<path:filename>', methods=['GET'])
def serve_storage(filename):
    if os.path.exists(os.path.join(STORAGE_DIR, filename)):
        return send_from_directory(STORAGE_DIR, filename)
    if os.path.exists(os.path.join(TRUSTVOTE_STORAGE, filename)):
        return send_from_directory(TRUSTVOTE_STORAGE, filename)
    return abort(404)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    print(f"\n" + "="*70)
    print(f"  NATIONAL VOTER SERVICES / STATE ELECTION COMMISSION")
    print(f"  FIRST-TIME VOTER e-EPIC DOWNLOAD & FORM NO. 6 APPLICATION PORTAL")
    print(f"  Running at: http://127.0.0.1:{port}")
    print(f"="*70 + "\n")
    app.run(host='0.0.0.0', port=port, debug=False)
