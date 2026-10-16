import os
import sys
import sqlite3
import qrcode
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file, redirect, url_for, abort

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in [BASE_DIR, os.getcwd()]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from config import ID_CARDS_DIR, STORAGE_DIR
except ImportError:
    ID_CARDS_DIR = os.path.join(BASE_DIR, "id_cards")
    STORAGE_DIR = os.path.join(BASE_DIR, "storage")

from database import get_db_connection
from utils.card import create_voter_card, create_voting_pass
from utils.security import encrypt_voter_data

download_bp = Blueprint('download', __name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. PORTAL PAGE ROUTES (FIRST-TIME APPLICANT e-EPIC DOWNLOAD)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@download_bp.route('/voter/download', methods=['GET'])
@download_bp.route('/download-card', methods=['GET'])
@download_bp.route('/download_card', methods=['GET'])
@download_bp.route('/voter/portal', methods=['GET'])
@download_bp.route('/first_time_voter/download', methods=['GET'])
def download_card_page():
    """Renders the standalone public website for First-Time Applicant Voter ID Card download."""
    return render_template('download_card.html')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. APPLICATION STATUS & CARD CHECK API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@download_bp.route('/api/check_first_time_voter', methods=['POST'])
def check_first_time_voter():
    """
    Checks voter application status.
    Voter ID Card is ONLY available/generated if constituency ERO has APPROVED the application.
    """
    data = request.json or {}
    query = (data.get('query') or '').strip()
    dob   = (data.get('dob') or '').strip()

    if not query:
        return jsonify({
            'status': 'error',
            'message': 'Please enter your Application Reference Number, Voter ID (EPIC), Mobile Number, or Aadhaar.'
        }), 400

    clean_query = query.upper()
    clean_digits = ''.join(filter(str.isdigit, query))

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Flexible query search: by v_id (EPIC / Ref), mobile, aadhaar_no, or exact Name + DOB
        cursor.execute("""
            SELECT v.v_id, v.name, v.gender, v.dob, v.photo, v.district, v.constituency,
                   v.reg_date, v.assigned_booth_id, v.form6_file, v.relative_type, v.relative_name,
                   v.mobile, v.email, v.aadhaar_no, v.address_line, v.pincode, v.taluka,
                   v.ero_status, v.ero_remarks, v.ero_decided_by, v.ero_decided_at,
                   b.booth_code, b.booth_name, b.polling_station
            FROM voters v
            LEFT JOIN booths b ON v.assigned_booth_id = b.id
            WHERE UPPER(v.v_id) = ?
               OR (v.mobile IS NOT NULL AND v.mobile != '' AND v.mobile = ?)
               OR (v.aadhaar_no IS NOT NULL AND v.aadhaar_no != '' AND v.aadhaar_no = ?)
               OR (UPPER(v.name) = ? AND (? = '' OR v.dob = ?))
            LIMIT 1
        """, (clean_query, clean_digits if clean_digits else clean_query, clean_digits if clean_digits else clean_query, clean_query, dob, dob))

        row = cursor.fetchone()

        # If not found directly, try case-insensitive LIKE search on name if DOB provided
        if not row and len(query) >= 3 and dob:
            cursor.execute("""
                SELECT v.v_id, v.name, v.gender, v.dob, v.photo, v.district, v.constituency,
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
                'message': f'No application record found for "{query}". Please verify your Application Reference Number / Registered Mobile Number / EPIC.'
            })

        voter = dict(row)
        vid = voter['v_id']
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
                    'name': voter.get('name'),
                    'relative_name': voter.get('relative_name'),
                    'relative_type': voter.get('relative_type') or 'Father',
                    'dob': voter.get('dob'),
                    'gender': voter.get('gender'),
                    'district': voter.get('district') or 'Pune',
                    'constituency': voter.get('constituency') or 'Shivaji Nagar',
                    'reg_date': voter.get('reg_date'),
                    'mobile': voter.get('mobile'),
                    'booth_code': voter.get('booth_code') or 'General',
                    'booth_name': voter.get('booth_name') or 'Constituency Polling Station',
                    'form6_file': voter.get('form6_file')
                },
                'ero_jurisdiction': f"{voter.get('constituency') or 'Shivaji Nagar'}, {voter.get('district') or 'Pune'}",
                'explanation': 'In accordance with State Election Commission security protocols, official Voter ID Cards (e-EPIC) are generated and issued ONLY after formal verification & approval by the Constituency Electoral Registration Officer (ERO).'
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
            # Ensure physical card & voting pass files exist
            os.makedirs(ID_CARDS_DIR, exist_ok=True)
            card_file = os.path.join(ID_CARDS_DIR, f"{vid}_final_card.png")
            pass_file = os.path.join(ID_CARDS_DIR, f"{vid}_qr_pass.png")
            qr_file   = os.path.join(ID_CARDS_DIR, f"{vid}_qr.png")

            if not os.path.exists(card_file) or not os.path.exists(pass_file):
                p_path = voter.get('photo') or os.path.join(STORAGE_DIR, f"{vid}.jpg")
                v_name = voter.get('name') or 'Citizen'
                v_dob  = voter.get('dob') or '2000-01-01'
                v_gen  = voter.get('gender') or 'Male'
                v_dist = voter.get('district') or 'Pune'
                v_const = voter.get('constituency') or 'Shivaji Nagar'

                try:
                    encrypted_token = encrypt_voter_data(vid, v_name, v_dob, v_gen, p_path)
                    qr = qrcode.QRCode(
                        version=None,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(encrypted_token)
                    qr.make(fit=True)
                    qr_img = qr.make_image(fill_color="black", back_color="white")
                    qr_img.save(qr_file)

                    create_voter_card(vid, v_name, v_dob, v_gen, p_path, v_dist, v_const)
                    create_voting_pass(vid, v_name, v_dist, v_const)
                except Exception as gen_err:
                    print(f"[Download API] On-demand card generation warning for {vid}: {gen_err}")

            return jsonify({
                'status': 'APPROVED',
                'message': 'Official Electoral Roll Approval Verified! Your Certified Voter ID Card and Digital Voting Pass are ready for download.',
                'voter': {
                    'v_id': vid,
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
                'card_preview_url': f"/id_cards/{vid}_final_card.png",
                'pass_preview_url': f"/id_cards/{vid}_qr_pass.png",
                'download_card_url': f"/voter/download/card/{vid}",
                'download_pass_url': f"/voter/download/pass/{vid}",
                'certificate_url': f"/voter/certificate/{vid}"
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. DIRECT CARD FILE DOWNLOAD ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@download_bp.route('/voter/download/card/<vid>', methods=['GET'])
def download_voter_card_file(vid):
    """Downloads the official Voter ID Card PNG as an attachment (Only if ERO Approved)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT v_id, name, ero_status FROM voters WHERE UPPER(v_id) = ?", (vid.upper(),))
        row = cursor.fetchone()
        if not row:
            return "Voter record not found.", 404
        if (row['ero_status'] or '').upper() != 'APPROVED':
            return "Unauthorized: Voter ID card has not been approved by the Constituency ERO yet.", 403

        card_path = os.path.join(ID_CARDS_DIR, f"{row['v_id']}_final_card.png")
        if not os.path.exists(card_path):
            return "Card file not generated.", 404

        return send_file(
            card_path,
            as_attachment=True,
            download_name=f"SEC_Maharashtra_Voter_ID_{row['v_id']}.png",
            mimetype="image/png"
        )
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@download_bp.route('/voter/download/pass/<vid>', methods=['GET'])
def download_voting_pass_file(vid):
    """Downloads the official QR Voting Pass PNG as an attachment (Only if ERO Approved)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT v_id, name, ero_status FROM voters WHERE UPPER(v_id) = ?", (vid.upper(),))
        row = cursor.fetchone()
        if not row:
            return "Voter record not found.", 404
        if (row['ero_status'] or '').upper() != 'APPROVED':
            return "Unauthorized: Voting pass has not been approved by the Constituency ERO yet.", 403

        pass_path = os.path.join(ID_CARDS_DIR, f"{row['v_id']}_qr_pass.png")
        if not os.path.exists(pass_path):
            return "Voting pass file not generated.", 404

        return send_file(
            pass_path,
            as_attachment=True,
            download_name=f"SEC_Maharashtra_Voting_Pass_{row['v_id']}.png",
            mimetype="image/png"
        )
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@download_bp.route('/voter/certificate/<vid>', methods=['GET'])
def voter_certificate_view(vid):
    """Renders a printable official e-EPIC Certificate & Voter Slip."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.*, b.booth_code, b.booth_name, b.polling_station
            FROM voters v
            LEFT JOIN booths b ON v.assigned_booth_id = b.id
            WHERE UPPER(v.v_id) = ?
        """, (vid.upper(),))
        row = cursor.fetchone()
        if not row:
            return "Voter record not found.", 404
        voter = dict(row)
        if (voter.get('ero_status') or '').upper() != 'APPROVED':
            return "Certificate unavailable: Application is still pending ERO approval.", 403

        return render_template('voter_certificate.html', voter=voter)
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
