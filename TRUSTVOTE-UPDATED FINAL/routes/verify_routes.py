import os
import cv2
import base64
from datetime import datetime
from flask import Blueprint, request, render_template, jsonify, session, redirect, url_for
from database import get_db_connection
from utils.face import decode_base64_image, extract_face_roi, compare_faces
from utils.security import decrypt_voter_data
from utils.qr_decoder import decode_qr_from_image

verify_bp = Blueprint('verify', __name__)

@verify_bp.route('/scan')
def scan_page():
    if not session.get('booth_logged_in'):
        return redirect(url_for('officer.booth_login'))
    return render_template('scan.html')

@verify_bp.route('/api/scan_qr_image', methods=['POST'])
def scan_qr_image():
    if not session.get('booth_logged_in'):
        return jsonify({"status": "Error", "message": "Unauthorized"}), 401
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

        if election:
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
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
                conn.close()

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
    if not session.get('booth_logged_in'):
        return jsonify({"status": "Error", "message": "Unauthorized"}), 401
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

        if election:
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
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
                conn.close()

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
    if not session.get('booth_logged_in'):
        return jsonify({"match": False, "message": "Unauthorized"}), 401
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
