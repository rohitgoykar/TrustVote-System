import os
import sys
import random
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
        reg_type   = data.get('reg_type', 'first_time').strip().lower()
        is_existing = (reg_type == 'existing')
        vid        = (data.get('v_id') or '').strip().upper()
        
        app_id = None
        if not is_existing:
            # Generate official Application ID for first-time voter applicant
            app_id = f"MHAPP{datetime.now().strftime('%y%m%d')}{random.randint(1000, 9999)}"
            if not vid:
                vid = app_id
        else:
            if not vid:
                vid = f"MH{datetime.now().strftime('%y%m%d')}{random.randint(1000, 9999)}"

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
                return jsonify({"status": "Error", "message": "⚠️ Eligibility Error: Voter must be 18 years of age or older to register."})
        except Exception as e:
            return jsonify({"status": "Error", "message": f"⚠️ Invalid Date of Birth format: {e}"})

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
                "message": f"⚠️ Cross-Constituency Duplicate Blocked: Citizen '{existing['name']}' (Voter ID: {vid}) is already registered in Constituency: '{ext_const}', District: '{ext_dist}'. Dual-constituency registration is strictly prohibited by SEC Maharashtra."
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
                "message": f"⚠️ Biometric Cross-Constituency Duplicate Detected: This citizen's face is already registered as '{dup_name}' (Voter ID: {dup_vid}) in Constituency: '{dup_const}', District: '{dup_dist}'. Multiple registrations across constituencies are blocked."
            })

        # ── Form 6 Specific Details ──────────────────────────────────────────
        relative_type = data.get('relative_type', 'Father').strip()
        relative_name = data.get('relative_name', '').strip()
        if not relative_name and data.get('father_name'):
            relative_name = data.get('father_name').strip()
        mobile = data.get('mobile', '').strip()
        email = data.get('email', '').strip()
        aadhaar_no = data.get('aadhaar_no', '').strip()
        address_line = data.get('address_line', '').strip()
        pincode = data.get('pincode', '').strip()
        taluka = data.get('taluka', '').strip()
        dob_proof_type = data.get('dob_proof_type', '').strip()

        # Handle Form 6 File Upload (PDF / Image)
        form6_filename = None
        form6_file = request.files.get('form6_upload') or request.files.get('form6_file')
        if form6_file and form6_file.filename:
            f6_dir = os.path.join(STORAGE_DIR, "form6_uploads")
            os.makedirs(f6_dir, exist_ok=True)
            ext = os.path.splitext(form6_file.filename)[1].lower()
            if not ext:
                ext = ".pdf"
            form6_filename = f"{vid}_form6{ext}"
            form6_path = os.path.join(f6_dir, form6_filename)
            form6_file.save(form6_path)

        # ── 3. Save photo (only after all duplicate checks pass) ──────────────
        p_path = os.path.join(STORAGE_DIR, vid + ".jpg")
        with open(p_path, "wb") as f:
            f.write(base64.b64decode(photo_data.split(",")[1]))

        # ── 4. Save to DB ────────────────────────────────────────────────────
        ero_status_val = 'APPROVED' if is_existing else 'PENDING'
        ero_remarks_val = 'Existing Certified Voter Enrolment' if is_existing else 'Form 6 Application (First-Time Voter) — Forwarded to Constituency ERO'

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
                                       reg_date, dob, assigned_booth_id,
                                       form6_file, relative_type, relative_name, mobile, email,
                                       aadhaar_no, address_line, pincode, taluka, dob_proof_type,
                                       ero_status, ero_remarks, application_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (vid, name, data['gender'], p_path, district, constituency,
                 gp, ps, zp, mnc, np, npt,
                 gp_name, ps_name, zp_name, mnc_name, np_name, npt_name,
                 today, dob, assigned_booth_id,
                 form6_filename, relative_type, relative_name, mobile, email,
                 aadhaar_no, address_line, pincode, taluka, dob_proof_type,
                 ero_status_val, ero_remarks_val, app_id)
            )
            conn_ins.commit()
        finally:
            if conn_ins:
                try: conn_ins.close()
                except Exception: pass

        # If existing voter -> Generate card immediately
        if is_existing:
            try:
                os.makedirs(ID_CARDS_DIR, exist_ok=True)
                encrypted_token = encrypt_voter_data(vid, name, dob, data['gender'], p_path)
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
            except Exception as card_e:
                print(f"[Existing Reg] Card generation note: {card_e}")

        return jsonify({
            "status": "Success",
            "v_id": vid,
            "application_id": app_id,
            "reg_type": reg_type,
            "ero_status": ero_status_val,
            "message": "Existing voter enrolled successfully." if is_existing else f"Form 6 Application submitted. Application ID: {app_id}"
        })

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
                'message': f"⚠️ Voter ID '{vid}' is already registered under '{row['name']}' in Constituency '{row['constituency']}' ({row['district']})."
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
    
    voter_info = None
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT v_id, application_id, name, district, constituency, ero_status, ero_remarks FROM voters WHERE v_id = ? OR application_id = ?", (vid, vid))
        voter_info = cursor.fetchone()
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    v_name = voter_info['name'] if voter_info else 'Applicant'
    v_dist = voter_info['district'] if voter_info else 'Maharashtra'
    v_const = voter_info['constituency'] if voter_info else 'Constituency'
    v_status = (voter_info['ero_status'] if voter_info else 'PENDING').upper()
    v_app_id = (voter_info['application_id'] if voter_info and voter_info['application_id'] else vid)

    return render_template_string("""
    <!DOCTYPE html>
    <html lang="mr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>TrustVote - नोंदणी पावती (Registration Receipt)</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800;900&family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
        <style>
            * { margin:0; padding:0; box-sizing:border-box; font-family:'Plus Jakarta Sans', 'Inter', sans-serif; }
            body {
                background: linear-gradient(135deg, #f8fafc 0%, #eff6ff 50%, #f0fdf4 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 24px;
            }
            .success-card {
                background: rgba(255, 255, 255, 0.98);
                border-radius: 28px;
                padding: 40px;
                max-width: 640px;
                width: 100%;
                text-align: center;
                box-shadow: 0 25px 60px -15px rgba(15, 23, 42, 0.12), 0 0 0 1px rgba(226, 232, 240, 0.8);
                backdrop-filter: blur(12px);
            }
            .badge-icon {
                width: 72px;
                height: 72px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 18px;
                font-size: 32px;
            }
            .badge-icon.approved { background: #f0fdf4; color: #16a34a; border: 2px solid #86efac; }
            .badge-icon.pending  { background: #eff6ff; color: #2563eb; border: 2px solid #bfdbfe; }
            h1 { font-size: 22px; font-weight: 900; color: #0f172a; margin-bottom: 6px; }
            p { font-size: 13.5px; color: #64748b; margin-bottom: 20px; }
            
            .app-id-banner {
                background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
                color: white;
                border-radius: 20px;
                padding: 22px;
                margin-bottom: 24px;
                box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.35);
                text-align: center;
            }
            .app-id-title {
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                color: #bfdbfe;
                margin-bottom: 6px;
            }
            .app-id-code {
                font-size: 24px;
                font-weight: 900;
                font-family: 'JetBrains Mono', monospace;
                letter-spacing: 2px;
                background: rgba(255, 255, 255, 0.15);
                display: inline-block;
                padding: 6px 18px;
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.25);
                margin-bottom: 8px;
            }
            .app-id-note {
                font-size: 12px;
                color: #dbeafe;
                line-height: 1.5;
            }

            .portal-cta-box {
                background: #f0fdf4;
                border: 2px solid #86efac;
                border-radius: 18px;
                padding: 18px;
                margin-bottom: 24px;
                text-align: left;
            }
            .portal-cta-header {
                font-size: 13px;
                font-weight: 800;
                color: #166534;
                margin-bottom: 6px;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .portal-cta-desc {
                font-size: 12px;
                color: #15803d;
                margin-bottom: 12px;
                line-height: 1.5;
            }

            .step-box {
                background: #f8fafc;
                border: 1.5px solid #e2e8f0;
                border-radius: 18px;
                padding: 20px;
                margin-bottom: 24px;
                text-align: left;
            }
            .step-item {
                display: flex;
                align-items: flex-start;
                gap: 12px;
                margin-bottom: 14px;
            }
            .step-item:last-child { margin-bottom: 0; }
            .step-num {
                width: 26px;
                height: 26px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: 800;
                flex-shrink: 0;
            }
            .step-done { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
            .step-active { background: #eff6ff; color: #1d4ed8; border: 1px solid #93c5fd; }
            .step-wait { background: #e2e8f0; color: #64748b; }
            .step-text h4 { font-size: 13px; font-weight: 800; color: #1e293b; margin-bottom: 2px; }
            .step-text p { font-size: 12px; color: #64748b; margin-bottom: 0; }

            .btn {
                display: block;
                padding: 13px 18px;
                border-radius: 12px;
                font-weight: 700;
                font-size: 13.5px;
                text-decoration: none;
                margin-bottom: 10px;
                transition: all 0.2s;
                text-align: center;
            }
            .btn-portal {
                background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
                color: white;
                box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35);
            }
            .btn-portal:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(37, 99, 235, 0.45); }
            .btn-primary { background: #16a34a; color: white; }
            .btn-primary:hover { background: #15803d; }
            .btn-outline { background: #f8fafc; color: #334155; border: 1.5px solid #cbd5e1; }
            .btn-outline:hover { background: #f1f5f9; }
        </style>
    </head>
    <body>
        <div class="success-card">
            {% if v_status == 'APPROVED' %}
                <div class="badge-icon approved">✓</div>
                <h1>मतदार नोंदणी यशस्वी! (Voter Enrolled)</h1>
                <p>Voter ID: <span style="font-family:monospace; font-weight:800; color:#0284c7;">{{ vid }}</span></p>

                <div style="background:#f8fafc; border:1.5px solid #e2e8f0; border-radius:16px; padding:16px; margin-bottom:20px; text-align:left;">
                    <div style="font-size:12px; font-weight:700; color:#475569; margin-bottom:10px; text-transform:uppercase; letter-spacing:0.5px;">Download Certified Documents:</div>
                    <a href="/download_card/{{ vid }}" class="btn btn-primary">
                        📥 Download Official Voter Identity Card
                    </a>
                    <a href="/download_qr/{{ vid }}" class="btn btn-outline" style="background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe;">
                        📱 Download Scanner QR Code (_qr.png)
                    </a>
                </div>
            {% else %}
                <div class="badge-icon pending">📋</div>
                <h1>Form No. 6 Application Submitted!</h1>
                <p>Applicant: <strong>{{ v_name }}</strong> • {{ v_const }} ({{ v_dist }})</p>

                <!-- ── OFFICIAL APPLICATION ID GENERATED ── -->
                <div class="app-id-banner">
                    <div class="app-id-title">Generated Application ID (अर्जाचा क्रमांक)</div>
                    <div class="app-id-code">{{ v_app_id }}</div>
                    <div class="app-id-note">
                        Please note down this <strong>Application ID</strong>. The applicant can log in to the <strong>First-Time Voter e-EPIC Portal</strong> using this ID and their Date of Birth.
                    </div>
                </div>

                <!-- ── FIRST-TIME VOTER EPIC PORTAL CTA ── -->
                <div class="portal-cta-box">
                    <div class="portal-cta-header">
                        <span>🚀</span> FIRST TIME VOTER EPIC PORTAL (Standalone Web App)
                    </div>
                    <div class="portal-cta-desc">
                        First-time applicants can track their Form 6 verification and instantly download their official digital <strong>e-EPIC Voter Card & QR Pass</strong> upon ERO approval at port <strong>5001</strong>.
                    </div>
                    <a href="http://127.0.0.1:5001/login" target="_blank" class="btn btn-portal" style="margin-bottom:0;">
                        🔗 Go to First-Time Voter e-EPIC Portal (Port 5001) →
                    </a>
                </div>

                <div class="step-box">
                    <div class="step-item">
                        <div class="step-num step-done">✓</div>
                        <div class="step-text">
                            <h4>Step 1: Form 6 Registered & Application ID Generated</h4>
                            <p>Application ID: <code>{{ v_app_id }}</code> successfully assigned and saved.</p>
                        </div>
                    </div>
                    <div class="step-item">
                        <div class="step-num step-active">2</div>
                        <div class="step-text">
                            <h4>Step 2: Forwarded to Constituency ERO (Current Stage)</h4>
                            <p>Assigned to ERO for <strong>{{ v_const }} ({{ v_dist }})</strong> for statutory verification.</p>
                        </div>
                    </div>
                    <div class="step-item">
                        <div class="step-num step-wait">3</div>
                        <div class="step-text">
                            <h4>Step 3: ERO Approval & e-EPIC Card Generation</h4>
                            <p>Log into <a href="http://127.0.0.1:5001/login" target="_blank" style="color:#2563eb; font-weight:700;">First-Time Voter Portal</a> with Application ID + DOB to download card once certified.</p>
                        </div>
                    </div>
                </div>
            {% endif %}

            <a href="/register_page" class="btn btn-primary">
                + नवीन मतदार नोंदणी करा (New Registration)
            </a>
            <a href="/" class="btn btn-outline" style="border:none; color:#64748b;">
                मुख्यपृष्ठावर जा (Home)
            </a>
        </div>
    </body>
    </html>
    """, vid=vid, v_name=v_name, v_dist=v_dist, v_const=v_const, v_status=v_status, v_app_id=v_app_id)

@register_bp.route('/download_card/<vid>')
def download_card(vid):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT v_id, name, ero_status, ero_remarks FROM voters WHERE v_id = ?", (vid,))
        voter = cursor.fetchone()
        if not voter:
            return "Voter record not found", 404
        if (voter['ero_status'] or 'PENDING').upper() != 'APPROVED':
            return f"""
            <div style="font-family:sans-serif; text-align:center; padding:40px;">
                <h2 style="color:#d97706;">⚠️ Voter ID Card Pending ERO Approval</h2>
                <p>Voter ID Card for <strong>{vid}</strong> ({voter['name']}) has not been certified yet.</p>
                <p>Status: <strong>{voter['ero_status']}</strong></p>
                <p>Remarks: {voter['ero_remarks']}</p>
                <p>The card will be available for download once the Electoral Registration Officer (ERO) approves the application.</p>
            </div>
            """, 403
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    card_path = os.path.join(ID_CARDS_DIR, f"{vid}_final_card.png")
    if os.path.exists(card_path):
        return send_file(card_path, as_attachment=True, download_name=f"VoterCard_{vid}.png")
    return "Card file is being generated upon ERO approval", 404

@register_bp.route('/download_qr/<vid>')
def download_qr(vid):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT v_id, name, ero_status FROM voters WHERE v_id = ?", (vid,))
        voter = cursor.fetchone()
        if not voter:
            return "Voter record not found", 404
        if (voter['ero_status'] or 'PENDING').upper() != 'APPROVED':
            return "QR Pass is pending ERO approval", 403
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    pass_path = os.path.join(ID_CARDS_DIR, f"{vid}_qr_pass.png")
    if os.path.exists(pass_path):
        return send_file(pass_path, as_attachment=True, download_name=f"VotingPass_{vid}.png")
    qr_path = os.path.join(ID_CARDS_DIR, f"{vid}_qr.png")
    if os.path.exists(qr_path):
        return send_file(qr_path, as_attachment=True, download_name=f"ScannerQR_{vid}.png")
    return "QR file not found", 404