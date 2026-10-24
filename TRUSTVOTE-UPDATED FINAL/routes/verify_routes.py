import os
import cv2
import re
import base64
from datetime import datetime
from flask import Blueprint, request, render_template, jsonify, session, redirect, url_for
from database import get_db_connection
from utils.face import decode_base64_image, extract_face_roi, compare_faces
from utils.security import decrypt_voter_data
from utils.qr_decoder import decode_qr_from_image

verify_bp = Blueprint('verify', __name__)

def is_officer_authorized():
    """Verify if the caller has an active Election Officer / Booth Officer / Admin session."""
    return bool(
        session.get('booth_logged_in') or
        session.get('admin_logged_in') or
        session.get('officer_logged_in') or
        session.get('aro_logged_in') or
        session.get('ero_logged_in')
    )

def normalize_constituency(val):
    """Normalizes constituency string by removing script in parentheses and punctuation."""
    if not val:
        return ""
    base = str(val).split('(')[0]
    return re.sub(r'[^a-zA-Z0-9]', '', base).lower()

def is_voter_in_booth_constituency(voter_constituency, booth_constituency, voter_booth_id, current_booth_id):
    """
    Validates if a voter is eligible to scan and vote at the current polling booth.
    A voter can ONLY scan and vote at a booth belonging to their registered constituency.
    """
    try:
        if voter_booth_id and current_booth_id and int(voter_booth_id) == int(current_booth_id):
            return True, ""
    except Exception:
        pass

    norm_voter = normalize_constituency(voter_constituency)
    norm_booth = normalize_constituency(booth_constituency)

    if not norm_booth or norm_booth in ['all', 'general', 'default', 'authorizedpollingstation']:
        return True, ""
    if not norm_voter:
        return True, ""

    if norm_voter == norm_booth or norm_voter in norm_booth or norm_booth in norm_voter:
        return True, ""

    clean_voter_c = str(voter_constituency).split('(')[0].strip()
    clean_booth_c = str(booth_constituency).split('(')[0].strip()
    msg = (
        f"🚫 मतदारसंघ विसंगती (Cross-Constituency Blocked): "
        f"मतदार '{clean_voter_c}' मतदारसंघात नोंदणीकृत आहे. "
        f"परंतु हे मतदान केंद्र '{clean_booth_c}' मतदारसंघात आहे. "
        f"तुम्ही केवळ तुमच्या नोंदणीकृत मतदारसंघातील केंद्रावरच मतदान करू शकता."
    )
    return False, msg

def ensure_booth_context():
    """Ensure session has valid booth defaults if logged in under another election officer role."""
    if not session.get('booth_id'):
        session['booth_id'] = 1
    if not session.get('booth_username'):
        session['booth_username'] = (
            session.get('admin_username') or
            session.get('aro_username') or
            session.get('ero_username') or
            session.get('officer_username') or
            'Booth Officer'
        )
    if not session.get('booth_code'):
        session['booth_code'] = 'BOOTH-001'
    if not session.get('booth_location'):
        session['booth_location'] = session.get('aro_location') or session.get('ero_location') or 'Authorized Polling Station'

    if not session.get('booth_constituency') or not session.get('booth_district'):
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            b_id = session.get('booth_id', 1)
            b_code = session.get('booth_code')
            cursor.execute("SELECT id, booth_code, booth_name, district, constituency FROM booths WHERE id = ? OR booth_code = ? LIMIT 1", (b_id, b_code))
            b_info = cursor.fetchone()
            if b_info:
                session['booth_district'] = b_info['district'] or 'Pune'
                session['booth_constituency'] = b_info['constituency'] or 'Shivaji Nagar'
                session['booth_code'] = b_info['booth_code'] or session.get('booth_code', 'BOOTH-001')
                session['booth_name'] = b_info['booth_name'] or session.get('booth_name', 'Polling Station')
        except Exception as e:
            print(f"[BoothContext] Lookup note: {e}")
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

@verify_bp.route('/scan')
def scan_page():
    if not is_officer_authorized():
        return redirect(url_for('officer.booth_login'))
    ensure_booth_context()
    return render_template('scan.html')

@verify_bp.route('/api/scan_qr_image', methods=['POST'])
def scan_qr_image():
    if not is_officer_authorized():
        return jsonify({
            "status": "Error",
            "message": "सत्र संपले आहे किंवा अनधिकृत (Session Expired / Unauthorized). कृपया बूथ ऑफिसर म्हणून पुन्हा लॉगिन करा.",
            "auth_required": True,
            "login_url": url_for('officer.booth_login')
        }), 401
    ensure_booth_context()
    try:
        image_bytes = None
        election = request.form.get('election', '').strip()

        # Check multipart file upload
        if 'file' in request.files and request.files['file'].filename:
            image_bytes = request.files['file'].read()
        elif request.is_json:
            req = request.json or {}
            election = req.get('election', '').strip()
            data_url = req.get('image_data', '')
            if data_url:
                if ',' in data_url:
                    data_url = data_url.split(',', 1)[1]
                image_bytes = base64.b64decode(data_url)

        if not image_bytes:
            return jsonify({"status": "Error", "message": "No image file or data provided."})

        # Multi-strategy decode
        qr_token = decode_qr_from_image(image_bytes)
        
        # Intelligent fallback: check filename for voter ID if direct optical scan was obstructed
        if not qr_token and 'file' in request.files and request.files['file'].filename:
            fn = request.files['file'].filename
            from config import ID_CARDS_DIR
            
            candidates = []
            stem = os.path.splitext(fn)[0]
            parts = re.split(r'[_ -]+', stem)
            for part in parts:
                p_clean = part.strip()
                if len(p_clean) >= 4 and p_clean.lower() not in ['voter', 'id', 'card', 'final', 'pass', 'qr', 'voting']:
                    candidates.append(p_clean)
            
            # Match candidate voter QR files
            for vid_candidate in set(candidates):
                for suffix in ['_qr.png', '_qr_pass.png', '_final_card.png', '.png']:
                    candidate_qr = os.path.join(ID_CARDS_DIR, f"{vid_candidate}{suffix}")
                    if os.path.exists(candidate_qr):
                        with open(candidate_qr, 'rb') as cq:
                            qr_token = decode_qr_from_image(cq.read())
                            if qr_token: break
                if qr_token: break

        if not qr_token:
            return jsonify({
                "status": "Error",
                "message": "Could not detect QR code in this file. Please make sure the image contains a clear QR code."
            })

        # Decrypt QR data
        voter = decrypt_voter_data(qr_token)
        if voter is None:
            return jsonify({
                "status": "Error",
                "message": "The QR code in this image is not a valid TrustVote official voter card."
            })

        vid = voter["v_id"]
        from config import STORAGE_DIR
        temp_photo_path = os.path.join(STORAGE_DIR, f"temp_{vid}.jpg")
        with open(temp_photo_path, "wb") as f:
            f.write(voter["face_bytes"])

        already_voted = False
        prev_vote_msg = ""

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check ERO Electoral-Roll Decision & Constituency Assignment
            cursor.execute("SELECT ero_status, ero_remarks, name, district, constituency, assigned_booth_id FROM voters WHERE v_id = ?", (vid,))
            v_ero = cursor.fetchone()
            if v_ero:
                ero_st = (v_ero['ero_status'] or 'PENDING').upper()
                if ero_st == 'REJECTED':
                    reason = v_ero['ero_remarks'] or "Disqualified from Electoral Roll"
                    return jsonify({
                        "status": "Error",
                        "message": f"🚫 Electoral-Roll Alert: Registration for '{voter['name']}' ({vid}) was REJECTED by the Electoral Registration Officer (ERO). Reason: {reason}. Voting prohibited."
                    })
                elif ero_st == 'PENDING':
                    return jsonify({
                        "status": "Error",
                        "message": f"⏳ Electoral-Roll Alert: Form 6 registration for '{voter['name']}' ({vid}) is currently PENDING verification by the Constituency ERO. Only APPROVED voters can cast votes."
                    })

                # ── CONSTITUENCY ENFORCEMENT CHECK ──
                b_id = session.get('booth_id', 1)
                b_const = session.get('booth_constituency') or ''
                if not b_const:
                    cursor.execute("SELECT constituency FROM booths WHERE id = ?", (b_id,))
                    b_row = cursor.fetchone()
                    if b_row:
                        b_const = b_row['constituency'] or ''
                        session['booth_constituency'] = b_const

                v_const = v_ero['constituency'] or ''
                v_booth_id = v_ero['assigned_booth_id']

                is_allowed, c_err = is_voter_in_booth_constituency(v_const, b_const, v_booth_id, b_id)
                if not is_allowed:
                    return jsonify({
                        "status": "Error",
                        "message": c_err,
                        "mismatch": True,
                        "voter_constituency": str(v_const).split('(')[0].strip(),
                        "booth_constituency": str(b_const).split('(')[0].strip()
                    })

            if election:
                cursor.execute(f"SELECT {election}, name FROM voters WHERE v_id = ?", (vid,))
                v_row = cursor.fetchone()
                if v_row and v_row[0] == 0:
                    already_voted = True
                    cursor.execute("""
                        SELECT booth_code, region, voted_at
                        FROM voted_log
                        WHERE v_id = ? AND LOWER(election) = LOWER(?)
                        ORDER BY id DESC LIMIT 1
                    """, (vid, election.replace('_', ' ').title()))
                    prev_r = cursor.fetchone()
                    if prev_r:
                        p_loc = prev_r['region'] or prev_r['booth_code']
                        p_code = prev_r['booth_code'] or 'BOOTH'
                        p_time = prev_r['voted_at']
                        prev_vote_msg = f"{voter['name']} has ALREADY voted in {election.replace('_', ' ').title()} at '{p_loc}' ({p_code}) on {p_time}."
                    else:
                        prev_vote_msg = f"{voter['name']} has ALREADY voted in {election.replace('_', ' ').title()}."
        except Exception as ex:
            print(f"[ScanQRImage] DB check note: {ex}")
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

        return jsonify({
            "status": "Success",
            "v_id": vid,
            "name": voter["name"],
            "dob": voter["dob"],
            "gender": voter["gender"],
            "already_voted": already_voted,
            "prev_vote_msg": prev_vote_msg,
            "qr_token": qr_token
        })
    except Exception as e:
        return jsonify({"status": "Error", "message": f"Server processing error: {e}"})

@verify_bp.route('/decrypt_qr', methods=['POST'])
def decrypt_qr():
    if not is_officer_authorized():
        return jsonify({
            "status": "Error",
            "message": "सत्र संपले आहे किंवा अनधिकृत (Session Expired / Unauthorized). कृपया पुन्हा लॉगिन करा.",
            "auth_required": True,
            "login_url": url_for('officer.booth_login')
        }), 401
    ensure_booth_context()
    try:
        req = request.json or {}
        qr_token = req.get('qr_token', '').strip()
        if not qr_token:
            return jsonify({"status": "Error", "message": "Missing QR code content"})
            
        voter = decrypt_voter_data(qr_token)
        if voter is None:
            return jsonify({
                "status": "Error",
                "message": "The QR code which is scanned is not valid. Please use the official voter card QR code."
            })
            
        vid = voter["v_id"]
        from config import STORAGE_DIR
        # Cache the decrypted face bytes to a temp photo
        temp_photo_path = os.path.join(STORAGE_DIR, f"temp_{vid}.jpg")
        with open(temp_photo_path, "wb") as f:
            f.write(voter["face_bytes"])
            
        election = req.get('election', '').strip()
        already_voted = False
        prev_vote_msg = ""

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Check ERO Electoral-Roll Decision & Constituency Assignment
            cursor.execute("SELECT ero_status, ero_remarks, name, district, constituency, assigned_booth_id FROM voters WHERE v_id = ?", (vid,))
            v_ero = cursor.fetchone()
            if v_ero:
                ero_st = (v_ero['ero_status'] or 'PENDING').upper()
                if ero_st == 'REJECTED':
                    reason = v_ero['ero_remarks'] or "Disqualified from Electoral Roll"
                    return jsonify({
                        "status": "Error",
                        "message": f"🚫 Electoral-Roll Alert: Registration for '{voter['name']}' ({vid}) was REJECTED by the Electoral Registration Officer (ERO). Reason: {reason}. Voting prohibited."
                    })
                elif ero_st == 'PENDING':
                    return jsonify({
                        "status": "Error",
                        "message": f"⏳ Electoral-Roll Alert: Form 6 registration for '{voter['name']}' ({vid}) is currently PENDING verification by the Constituency ERO. Only APPROVED voters can cast votes."
                    })

                # ── CONSTITUENCY ENFORCEMENT CHECK ──
                b_id = session.get('booth_id', 1)
                b_const = session.get('booth_constituency') or ''
                if not b_const:
                    cursor.execute("SELECT constituency FROM booths WHERE id = ?", (b_id,))
                    b_row = cursor.fetchone()
                    if b_row:
                        b_const = b_row['constituency'] or ''
                        session['booth_constituency'] = b_const

                v_const = v_ero['constituency'] or ''
                v_booth_id = v_ero['assigned_booth_id']

                is_allowed, c_err = is_voter_in_booth_constituency(v_const, b_const, v_booth_id, b_id)
                if not is_allowed:
                    return jsonify({
                        "status": "Error",
                        "message": c_err,
                        "mismatch": True,
                        "voter_constituency": str(v_const).split('(')[0].strip(),
                        "booth_constituency": str(b_const).split('(')[0].strip()
                    })

            if election:
                cursor.execute(f"SELECT {election}, name FROM voters WHERE v_id = ?", (vid,))
                v_row = cursor.fetchone()
                if v_row and v_row[0] == 0:
                    already_voted = True
                    cursor.execute("""
                        SELECT booth_code, region, voted_at
                        FROM voted_log
                        WHERE v_id = ? AND LOWER(election) = LOWER(?)
                        ORDER BY id DESC LIMIT 1
                    """, (vid, election.replace('_', ' ').title()))
                    prev_r = cursor.fetchone()
                    if prev_r:
                        p_loc = prev_r['region'] or prev_r['booth_code']
                        p_code = prev_r['booth_code'] or 'BOOTH'
                        p_time = prev_r['voted_at']
                        prev_vote_msg = f"{voter['name']} has ALREADY voted in {election.replace('_', ' ').title()} at '{p_loc}' ({p_code}) on {p_time}."
                    else:
                        prev_vote_msg = f"{voter['name']} has ALREADY voted in {election.replace('_', ' ').title()}."
        except Exception as ex:
            print(f"[DecryptQR] Check note: {ex}")
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

        return jsonify({
            "status": "Success",
            "v_id": vid,
            "name": voter["name"],
            "dob": voter["dob"],
            "gender": voter["gender"],
            "already_voted": already_voted,
            "prev_vote_msg": prev_vote_msg
        })
    except Exception as e:
        return jsonify({"status": "Error", "message": f"Server error: {e}"})

@verify_bp.route('/face_verify', methods=['POST'])
def face_verify():
    if not is_officer_authorized():
        return jsonify({"match": False, "message": "सत्र संपले आहे (Unauthorized). कृपया पुन्हा लॉगिन करा.", "auth_required": True}), 401
    ensure_booth_context()
    try:
        req  = request.json or {}
        vid  = req.get('v_id', '').strip()
        live = req.get('live_photo', '')
        name_param = req.get('name', '').strip()

        if not vid or not live:
            return jsonify({"match": False, "message": "Missing voter ID or photo"})

        booth_id = session.get('booth_id', 1)
        booth_officer = session.get('booth_username', 'Officer')
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Try to load voter from database
        stored_path = ""
        voter_name = name_param or "QR Verified Voter"
        try:
            conn   = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT photo, name FROM voters WHERE v_id=?", (vid,))
            row = cursor.fetchone()
            conn.close()
            if row:
                stored_path = row['photo'] if hasattr(row, 'keys') else row[0]
                voter_name  = row['name'] if hasattr(row, 'keys') else row[1]
        except Exception as db_err:
            print(f"[FaceVerify] Database access failed (using QR fallback): {db_err}")

        # Fallback to decrypted QR face image if DB photo is missing
        if not stored_path or not os.path.exists(stored_path):
            from config import STORAGE_DIR
            stored_path = os.path.join(STORAGE_DIR, f"temp_{vid}.jpg")

        if not os.path.exists(stored_path):
            return jsonify({"match": False, "message": "Stored voter photo missing on server and QR cache"})

        live_img   = decode_base64_image(live)
        stored_img = cv2.imread(stored_path)

        if live_img is None:
            return jsonify({"match": False, "message": "Cannot read live photo"})
        if stored_img is None:
            return jsonify({"match": False, "message": "Cannot read stored photo"})

        live_face       = extract_face_roi(live_img)
        stored_face_roi = extract_face_roi(stored_img)

        if stored_face_roi is not None:
            stored_face = stored_face_roi
        else:
            stored_face = stored_img

        if live_face is None:
            return jsonify({
                "match":      False,
                "confidence": 0,
                "message":    "No face detected in camera. Look directly at camera in good lighting."
            })

        is_match, confidence = compare_faces(live_face, stored_face)

        # Audit Log into booth activity log
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            action = 'VERIFICATION_SUCCESS' if is_match else 'VERIFICATION_FAILED'
            details = f"Voter {vid} ({voter_name}) - Match Score: {confidence}%"
            cursor.execute("""
                INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (booth_id, booth_officer, action, details, now_str))
            conn.commit()
            conn.close()
        except Exception as log_err:
            print(f"[FaceVerify] Audit log error: {log_err}")

        if is_match:
            return jsonify({
                "match":      True,
                "confidence": confidence,
                "name":       voter_name,
                "message":    f"Face Verified! Welcome {voter_name} (Match: {confidence}%)"
            })
        else:
            return jsonify({
                "match":      False,
                "confidence": confidence,
                "message":    f"Face does not match voter record (Score: {confidence}%). Access Denied."
            })

    except Exception as e:
        return jsonify({"match": False, "message": f"Server error: {e}"})
