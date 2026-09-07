import os
import sys
import base64
import qrcode
from datetime import datetime
from flask import Blueprint, request, render_template, jsonify, render_template_string, send_file, session, redirect, url_for

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in [BASE_DIR, os.getcwd()]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from config import STORAGE_DIR, ID_CARDS_DIR
except ImportError:
    STORAGE_DIR = os.path.join(BASE_DIR, "storage")
    ID_CARDS_DIR = os.path.join(BASE_DIR, "id_cards")

from database import get_db_connection
from utils.card import create_voter_card, create_voting_pass
from utils.face import decode_base64_image, check_duplicate_face
from utils.security import encrypt_voter_data
from utils.maharashtra_districts import MAHARASHTRA_DISTRICTS
from utils.maharashtra_local_bodies import DISTRICT_LOCAL_BODIES

register_bp = Blueprint('register', __name__)

@register_bp.route('/register_page')
def register_page():
    if not session.get('officer_logged_in'):
        return redirect(url_for('officer.officer_login'))
    return render_template('register.html')

@register_bp.route('/get_maharashtra_districts', methods=['GET'])
def get_maharashtra_districts():
    return jsonify({
        'status': 'success',
        'data': MAHARASHTRA_DISTRICTS
    })

@register_bp.route('/get_district_local_bodies', methods=['GET'])
def get_district_local_bodies():
    return jsonify({
        'status': 'success',
        'data': DISTRICT_LOCAL_BODIES
    })

@register_bp.route('/get_local_bodies', methods=['GET'])
def get_local_bodies():
    return jsonify({
        'status': 'success',
        'data': DISTRICT_LOCAL_BODIES
    })

@register_bp.route('/get_booths_list', methods=['GET'])
def get_booths_list():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, booth_code, booth_name, district, constituency, polling_station, region, status
            FROM booths
            ORDER BY district ASC, constituency ASC, id ASC
        """)
        booths = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': booths})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@register_bp.route('/register', methods=['POST'])
def register():
    if not session.get('officer_logged_in'):
        return jsonify({"status": "Error", "message": "Unauthorized: Officer not logged in"}), 401
    try:
        data       = request.form
        vid        = data['v_id'].strip()
        name       = data['name'].strip()
        photo_data = data['photo']
        dob        = data['dob'].strip()
        district   = data.get('district', 'Pune').strip()
        constituency = data.get('constituency', 'Shivaji Nagar').strip()
        assigned_booth_id = int(data.get('assigned_booth_id', 0))
        today      = datetime.now().strftime('%Y-%m-%d')

        # Local Body Selection Names
        mnc_name = data.get('mahanagarpalika_name', '').strip()
        zp_name  = data.get('zilha_parishad_name', '').strip()
        ps_name  = data.get('panchayat_samiti_name', '').strip()
        np_name  = data.get('nagar_parishad_name', '').strip()
        npt_name = data.get('nagar_panchayat_name', '').strip()
        gp_name  = data.get('gram_panchayat_name', '').strip()

        # If assigned_booth_id is not provided, resolve default booth for this constituency
        conn_b = None
        try:
            conn_b = get_db_connection()
            cursor = conn_b.cursor()
            if assigned_booth_id <= 0:
                cursor.execute("SELECT id FROM booths WHERE district=? AND constituency=? LIMIT 1", (district, constituency))
                b_row = cursor.fetchone()
                if b_row:
                    assigned_booth_id = b_row['id']
                else:
                    cursor.execute("SELECT id FROM booths WHERE district=? LIMIT 1", (district,))
                    b_dist = cursor.fetchone()
                    assigned_booth_id = b_dist['id'] if b_dist else 1
        finally:
            if conn_b:
                try: conn_b.close()
                except Exception: pass

        # ── Date of Birth validation (Age >= 18) ─────────────────────────────
        try:
            dob_date = datetime.strptime(dob, '%Y-%m-%d')
            today_dt = datetime.now()
            age = today_dt.year - dob_date.year - ((today_dt.month, today_dt.day) < (dob_date.month, dob_date.day))
            if age < 18:
                return jsonify({"status": "Error", "message": "️ Eligibility Error: Voter must be 18 years of age or older to register."})
        except Exception as e:
            return jsonify({"status": "Error", "message": f"️ Invalid Date of Birth format: {e}"})

        # NULL means "not registered for this election"
        # 1 means "registered and eligible to vote"
        gp = 1 if (data.get('gp') or gp_name) else None
        ps = 1 if (data.get('ps') or ps_name) else None
        zp = 1 if (data.get('zp') or zp_name) else None
        mnc = 1 if (data.get('mnc') or mnc_name) else None
        np = 1 if (data.get('np') or np_name) else None
        npt = 1 if (data.get('npt') or npt_name) else None

        # ── 1. Check if Voter ID already exists (with Constituency Context) ──
        conn_chk = None
        try:
            conn_chk = get_db_connection()
            cursor = conn_chk.cursor()
            cursor.execute("""
                SELECT v_id, name, district, constituency, reg_date
                FROM voters
                WHERE v_id = ?
            """, (vid,))
            existing = cursor.fetchone()
        finally:
            if conn_chk:
                try: conn_chk.close()
                except Exception: pass
        
        if existing:
            ext_dist = existing['district'] or 'Pune'
            ext_const = existing['constituency'] or 'Shivaji Nagar'
            return jsonify({
                "status": "Error",
                "message": f"️ Cross-Constituency Duplicate Blocked: Citizen '{existing['name']}' (Voter ID: {vid}) is already registered in Constituency: '{ext_const}', District: '{ext_dist}'. Dual-constituency registration is strictly prohibited by SEC Maharashtra."
            })

        # ── 2. Decode new photo and check for duplicate face ─────────────────
        new_img = decode_base64_image(photo_data)
        if new_img is None:
            return jsonify({"status": "Error", "message": "Could not read the captured photo. Please retake."})

        is_dup, dup_vid = check_duplicate_face(new_img, STORAGE_DIR)
        if is_dup:
            conn_dup = None
            try:
                conn_dup = get_db_connection()
                cursor = conn_dup.cursor()
                cursor.execute("""
                    SELECT v_id, name, district, constituency, reg_date
                    FROM voters
                    WHERE v_id = ?
                """, (dup_vid,))
                dup_record = cursor.fetchone()
            finally:
                if conn_dup:
                    try: conn_dup.close()
                    except Exception: pass

            if dup_record:
                dup_dist = dup_record['district'] or 'Pune'
                dup_const = dup_record['constituency'] or 'Shivaji Nagar'
                dup_name = dup_record['name']
            else:
                dup_dist = "Registered District"
                dup_const = "Registered Constituency"
                dup_name = "Registered Citizen"

            return jsonify({
                "status": "Error",
                "message": f"️ Biometric Cross-Constituency Duplicate Detected: This citizen's face is already registered as '{dup_name}' (Voter ID: {dup_vid}) in Constituency: '{dup_const}', District: '{dup_dist}'. Multiple registrations across constituencies are blocked."
            })

        # ── 3. Save photo (only after all duplicate checks pass) ──────────────
        p_path = os.path.join(STORAGE_DIR, vid + ".jpg")
        with open(p_path, "wb") as f:
            f.write(base64.b64decode(photo_data.split(",")[1]))

        # ── 4. Save to DB ────────────────────────────────────────────────────
        conn_ins = None
        try:
            conn_ins = get_db_connection()
            cursor = conn_ins.cursor()
            cursor.execute(
                """INSERT INTO voters (v_id, name, gender, photo, district, constituency,
                                       gram_panchayat, panchayat_samiti, zilha_parishad,
                                       mahanagarpalika, nagar_parishad, nagar_panchayat,
                                       gram_panchayat_name, panchayat_samiti_name, zilha_parishad_name,
                                       mahanagarpalika_name, nagar_parishad_name, nagar_panchayat_name,
                                       reg_date, dob, assigned_booth_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (vid, name, data['gender'], p_path, district, constituency,
                 gp, ps, zp, mnc, np, npt,
                 gp_name, ps_name, zp_name, mnc_name, np_name, npt_name,
                 today, dob, assigned_booth_id)
            )
            conn_ins.commit()
        finally:
            if conn_ins:
                try: conn_ins.close()
                except Exception: pass

        # Generate encrypted QR token containing voter details & face
        encrypted_token = encrypt_voter_data(vid, name, dob, data['gender'], p_path)
        
        # Make low-density QR code
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(encrypted_token)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img.save(os.path.join(ID_CARDS_DIR, vid + "_qr.png"))
        
        create_voter_card(vid, name, dob, data['gender'], p_path, district, constituency)
        create_voting_pass(vid, name, district, constituency)

        return jsonify({"status": "Success", "v_id": vid})

    except Exception as e:
        return jsonify({"status": "Error", "message": str(e)})

@register_bp.route('/check_voter_id', methods=['GET'])
def check_voter_id():
    if not session.get('officer_logged_in'):
        return jsonify({'exists': False})
    vid = request.args.get('v_id', '').strip()
    if not vid:
        return jsonify({'exists': False})
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v_id, name, district, constituency
            FROM voters
            WHERE v_id = ?
        """, (vid,))
        row = cursor.fetchone()
        if row:
            return jsonify({
                'exists': True,
                'name': row['name'],
                'district': row['district'],
                'constituency': row['constituency'],
                'message': f"️ Voter ID '{vid}' is already registered under '{row['name']}' in Constituency '{row['constituency']}' ({row['district']})."
            })
        return jsonify({'exists': False})
    except Exception as e:
        return jsonify({'exists': False, 'error': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@register_bp.route('/success/<vid>')
def success_page(vid):
    if not session.get('officer_logged_in'):
        return redirect(url_for('officer.officer_login'))
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="mr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>TrustVote - नोंदणी यशस्वी</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
        <style>
            * { margin:0; padding:0; box-sizing:border-box; font-family:'Inter', sans-serif; }
            body {
                background: #f8fafc;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            .success-card {
                background: white;
                border-radius: 24px;
                padding: 40px;
                max-width: 520px;
                width: 100%;
                text-align: center;
                box-shadow: 0 20px 40px -15px rgba(0,0,0,0.07);
                border: 1px solid #e2e8f0;
            }
            .badge-icon {
                width: 72px;
                height: 72px;
                background: #f0fdf4;
                color: #16a34a;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 20px;
                font-size: 32px;
            }
            h1 { font-size: 24px; font-weight: 800; color: #0f172a; margin-bottom: 8px; }
            p { font-size: 14px; color: #64748b; margin-bottom: 24px; }
            .v-id { font-size: 20px; font-weight: 800; color: #16a34a; letter-spacing: 1px; }
            .btn {
                display: block;
                padding: 14px;
                border-radius: 12px;
                font-weight: 700;
                font-size: 14px;
                text-decoration: none;
                margin-bottom: 12px;
                transition: all 0.2s;
            }
            .btn-primary { background: #16a34a; color: white; }
            .btn-primary:hover { background: #15803d; }
            .btn-outline { background: #f8fafc; color: #334155; border: 1.5px solid #cbd5e1; }
            .btn-outline:hover { background: #f1f5f9; }
        </style>
    </head>
    <body>
        <div class="success-card">
            <div class="badge-icon">✓</div>
            <h1>मतदार नोंदणी यशस्वी!</h1>
            <p>Voter ID: <span class="v-id">{{ vid }}</span></p>
            <div style="background:#f8fafc; border:1.5px solid #e2e8f0; border-radius:16px; padding:16px; margin-bottom:20px; text-align:left;">
                <div style="font-size:12px; font-weight:700; color:#475569; margin-bottom:10px; text-transform:uppercase; letter-spacing:0.5px;">Download Official Documents:</div>
                <a href="/download_card/{{ vid }}" class="btn btn-primary" style="text-align:center;">
                    Download Official Voter Identity Card
                </a>
                <a href="/download_qr/{{ vid }}" class="btn btn-outline" style="background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe; text-align:center;">
                    Download Scanner QR Code (_qr.png)
                </a>
            </div>
            <a href="/register_page" class="btn btn-outline">नवीन मतदार नोंदणी करा</a>
            <a href="/booth/login" class="btn btn-outline" style="background:#f0fdf4; color:#15803d; border-color:#bbf7d0;">Go to Polling Booth Scanner</a>
            <a href="/" class="btn btn-outline" style="border:none; color:#64748b;">मुख्यपृष्ठावर जा</a>
        </div>
    </body>
    </html>
    """, vid=vid)

@register_bp.route('/download_card/<vid>')
def download_card(vid):
    card_path = os.path.join(ID_CARDS_DIR, f"{vid}_final_card.png")
    if os.path.exists(card_path):
        return send_file(card_path, as_attachment=True, download_name=f"VoterCard_{vid}.png")
    return "Card file not found", 404

@register_bp.route('/download_qr/<vid>')
def download_qr(vid):
    pass_path = os.path.join(ID_CARDS_DIR, f"{vid}_qr_pass.png")
    if os.path.exists(pass_path):
        return send_file(pass_path, as_attachment=True, download_name=f"VotingPass_{vid}.png")
    qr_path = os.path.join(ID_CARDS_DIR, f"{vid}_qr.png")
    if os.path.exists(qr_path):
        return send_file(qr_path, as_attachment=True, download_name=f"ScannerQR_{vid}.png")
    return "QR file not found", 404