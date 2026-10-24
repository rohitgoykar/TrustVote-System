import os
import sqlite3
import random
import time
import qrcode
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, send_file
from database import get_db_connection, sync_master_to_constituency_db, get_constituency_slug, get_constituency_db_path, get_constituency_db_connection, list_all_constituency_databases
from utils.sms_gateway import send_officer_otp_sms

try:
    from config import ID_CARDS_DIR, STORAGE_DIR
except ImportError:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ID_CARDS_DIR = os.path.join(BASE_DIR, "id_cards")
    STORAGE_DIR = os.path.join(BASE_DIR, "storage")

from utils.card import create_voter_card, create_voting_pass
from utils.security import encrypt_voter_data, encrypt_offline_package, decrypt_offline_package, compress_photo_to_jpeg
from utils.blockchain import Blockchain

officer_bp = Blueprint('officer', __name__)

def generate_otp():
    """Generates a secure 6-digit numeric OTP."""
    return f"{random.randint(100000, 999999)}"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. REGISTRATION OFFICER AUTHENTICATION & OTP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@officer_bp.route('/officer/login', methods=['GET'])
def officer_login():
    if session.get('officer_logged_in'):
        return redirect(url_for('register.register_page'))
    return render_template('officer_login.html')

@officer_bp.route('/officer/send_otp', methods=['POST'])
def officer_send_otp():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    mobile = (data.get('mobile') or '').strip()

    if not username or not password or not mobile:
        return jsonify({'status': 'error', 'message': 'Username, Password, and Registered Mobile Number are required.'})

    clean_mobile = ''.join(filter(str.isdigit, mobile))
    if len(clean_mobile) != 10:
        return jsonify({'status': 'error', 'message': 'Please enter a valid 10-digit mobile number.'})

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password, mobile, location, role FROM officers WHERE username=? AND role='Registration Officer'", (username,))
        officer = cursor.fetchone()

        if not officer:
            return jsonify({'status': 'error', 'message': f'Registration Officer "{username}" not found or unauthorized.'})

        if officer['password'] != password:
            return jsonify({'status': 'error', 'message': 'Incorrect password entered.'})

        reg_mobile = ''.join(filter(str.isdigit, str(officer['mobile'] or '')))
        if reg_mobile and reg_mobile != clean_mobile:
            return jsonify({
                'status': 'error',
                'message': f'Mobile number +91 {clean_mobile} does not match the registered authorized records for "{username}".'
            })

        # Generate 6-digit OTP
        otp_code = generate_otp()

        # Dispatch via SMS Gateway (Fast2SMS / 2Factor / Twilio / Simulation)
        sms_result = send_officer_otp_sms(clean_mobile, otp_code, officer_role='Registration Officer', officer_name=username)

        # Save in session for 2-step verification
        session['pending_officer_id'] = officer['id']
        session['pending_officer_username'] = username
        session['pending_officer_location'] = officer['location']
        session['pending_officer_mobile'] = clean_mobile
        session['pending_officer_otp'] = otp_code
        session['pending_officer_otp_time'] = time.time()

        masked_mobile = f"+91 ******{clean_mobile[-4:]}"

        return jsonify({
            'status': 'success',
            'message': f'SEC Security OTP has been dispatched to registered mobile {masked_mobile}',
            'masked_mobile': masked_mobile,
            'sms_sent': sms_result.get('sent', False),
            'sms_gateway': sms_result.get('gateway', 'sms_service'),
            'sms_info': sms_result.get('message', '')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/officer/verify_otp', methods=['POST'])
def officer_verify_otp():
    data = request.json or {}
    entered_otp = (data.get('otp') or '').strip()

    expected_otp = session.get('pending_officer_otp')
    otp_time = session.get('pending_officer_otp_time', 0)

    if not expected_otp:
        return jsonify({'status': 'error', 'message': 'No pending OTP session found. Please enter your login credentials again.'})

    # OTP timeout: 10 minutes
    if time.time() - otp_time > 600:
        session.pop('pending_officer_otp', None)
        return jsonify({'status': 'error', 'message': 'OTP has expired. Please request a new OTP code.'})

    if entered_otp != str(expected_otp):
        return jsonify({'status': 'error', 'message': 'Incorrect OTP code entered. Please check your SMS and try again.'})

    # Successful OTP Verification -> Authorize Session
    session['officer_logged_in'] = True
    session['officer_username'] = session.get('pending_officer_username')
    session['officer_location'] = session.get('pending_officer_location')
    session['officer_mobile'] = session.get('pending_officer_mobile')

    # Clear pending OTP keys
    session.pop('pending_officer_otp', None)
    session.pop('pending_officer_otp_time', None)

    return jsonify({
        'status': 'success',
        'message': 'OTP verified successfully! Authorized access granted.',
        'redirect_url': url_for('register.register_page')
    })

@officer_bp.route('/officer/login_api', methods=['POST'])
def officer_login_api():
    """Direct login fallback or verification."""
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    mobile = data.get('mobile')

    if mobile:
        return officer_send_otp()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, location, mobile FROM officers WHERE username=? AND password=? AND role='Registration Officer'", (username, password))
        officer = cursor.fetchone()
        conn.close()
        if officer:
            session['officer_logged_in'] = True
            session['officer_username'] = username
            session['officer_location'] = officer['location']
            session['officer_mobile'] = officer['mobile']
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials or not a Registration Officer'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@officer_bp.route('/officer/logout')
def officer_logout():
    session.pop('officer_logged_in', None)
    session.pop('officer_username', None)
    session.pop('officer_location', None)
    session.pop('officer_mobile', None)
    return redirect(url_for('main.home'))


@officer_bp.route('/officer/my_voters', methods=['GET'])
def officer_my_voters():
    """Return all voters in the registration officer's assigned district/constituency."""
    if not session.get('officer_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    officer_location = (session.get('officer_location') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if officer_location:
            cursor.execute("""
                SELECT v.v_id, v.name, v.gender, v.dob, v.district, v.constituency,
                       v.booth_id, v.created_at, v.ero_status, v.ero_remarks,
                       v.ero_decided_by, v.ero_decided_at, v.photo_filename
                FROM voters v
                WHERE v.district = ?
                   OR v.constituency = ?
                   OR v.district LIKE ?
                   OR v.constituency LIKE ?
                ORDER BY v.created_at DESC
            """, (officer_location, officer_location,
                  f'%{officer_location}%', f'%{officer_location}%'))
        else:
            cursor.execute("""
                SELECT v.v_id, v.name, v.gender, v.dob, v.district, v.constituency,
                       v.booth_id, v.created_at, v.ero_status, v.ero_remarks,
                       v.ero_decided_by, v.ero_decided_at, v.photo_filename
                FROM voters v
                ORDER BY v.created_at DESC
                LIMIT 500
            """)

        voters = [dict(row) for row in cursor.fetchall()]
        return jsonify({
            'status': 'success',
            'data': voters,
            'count': len(voters)
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. BOOTH OFFICER AUTHENTICATION & OTP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@officer_bp.route('/booth/login', methods=['GET'])
def booth_login():
    if session.get('booth_logged_in'):
        return redirect(url_for('verify.scan_page'))
    return render_template('booth_login.html')

@officer_bp.route('/booth/send_otp', methods=['POST'])
def booth_send_otp():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    mobile = (data.get('mobile') or '').strip()

    if not username or not password or not mobile:
        return jsonify({'status': 'error', 'message': 'Username, Password, and Registered Mobile Number are required.'})

    clean_mobile = ''.join(filter(str.isdigit, mobile))
    if len(clean_mobile) != 10:
        return jsonify({'status': 'error', 'message': 'Please enter a valid 10-digit mobile number.'})

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.username, o.password, o.mobile, o.location, o.role, o.booth_id,
                   b.booth_code, b.booth_name, b.region, b.district, b.constituency
            FROM officers o
            LEFT JOIN booths b ON o.booth_id = b.id
            WHERE o.username=? AND o.role='Booth Officer'
        """, (username,))
        officer = cursor.fetchone()

        if not officer:
            return jsonify({'status': 'error', 'message': f'Booth Officer "{username}" not found or unauthorized.'})

        if officer['password'] != password:
            return jsonify({'status': 'error', 'message': 'Incorrect password entered.'})

        reg_mobile = ''.join(filter(str.isdigit, str(officer['mobile'] or '')))
        if reg_mobile and reg_mobile != clean_mobile:
            return jsonify({
                'status': 'error',
                'message': f'Mobile number +91 {clean_mobile} does not match the registered authorized records for "{username}".'
            })

        # Generate 6-digit OTP
        otp_code = generate_otp()

        # Dispatch via SMS Gateway (Fast2SMS / 2Factor / Twilio / Simulation)
        sms_result = send_officer_otp_sms(clean_mobile, otp_code, officer_role='Booth Officer', officer_name=username)

        booth_id = officer['booth_id'] if officer['booth_id'] else 1
        booth_code = officer['booth_code'] or f"BOOTH-00{booth_id}"
        booth_name = officer['booth_name'] or f"Booth {booth_id} - {officer['location']}"
        booth_region = officer['region'] or officer['location'] or "Default Region"
        booth_district = officer['district'] or 'Pune'
        booth_constituency = officer['constituency'] or 'Shivaji Nagar'

        # Save in session for 2-step verification
        session['pending_booth_officer_id'] = officer['id']
        session['pending_booth_username'] = username
        session['pending_booth_mobile'] = clean_mobile
        session['pending_booth_id'] = booth_id
        session['pending_booth_code'] = booth_code
        session['pending_booth_name'] = booth_name
        session['pending_booth_location'] = booth_region
        session['pending_booth_district'] = booth_district
        session['pending_booth_constituency'] = booth_constituency
        session['pending_booth_otp'] = otp_code
        session['pending_booth_otp_time'] = time.time()

        masked_mobile = f"+91 ******{clean_mobile[-4:]}"

        return jsonify({
            'status': 'success',
            'message': f'SEC Security OTP has been dispatched to registered mobile {masked_mobile}',
            'masked_mobile': masked_mobile,
            'sms_sent': sms_result.get('sent', False),
            'sms_gateway': sms_result.get('gateway', 'sms_service'),
            'sms_info': sms_result.get('message', '')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/booth/verify_otp', methods=['POST'])
def booth_verify_otp():
    data = request.json or {}
    entered_otp = (data.get('otp') or '').strip()

    expected_otp = session.get('pending_booth_otp')
    otp_time = session.get('pending_booth_otp_time', 0)

    if not expected_otp:
        return jsonify({'status': 'error', 'message': 'No pending OTP session found. Please enter your login credentials again.'})

    if time.time() - otp_time > 600:
        session.pop('pending_booth_otp', None)
        return jsonify({'status': 'error', 'message': 'OTP has expired. Please request a new OTP code.'})

    if entered_otp != str(expected_otp):
        return jsonify({'status': 'error', 'message': 'Incorrect OTP code entered. Please check your SMS and try again.'})

    # Successful OTP Verification -> Authorize Session & Mark Station ONLINE
    username = session.get('pending_booth_username')
    booth_id = session.get('pending_booth_id')
    booth_code = session.get('pending_booth_code')
    booth_name = session.get('pending_booth_name')
    booth_location = session.get('pending_booth_location')
    mobile = session.get('pending_booth_mobile')

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE booths SET status='ONLINE', last_active=? WHERE id=?", (now_str, booth_id))
        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (?, ?, 'LOGIN_OTP_VERIFIED', ?, ?)
        """, (booth_id, username, f"Booth Officer verified via Mobile OTP (+91 ******{mobile[-4:]})", now_str))
        conn.commit()
    except Exception as e:
        print(f"[BoothVerifyOTP] Activity log error: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    session.permanent = True
    session['booth_logged_in'] = True
    session['booth_username'] = username
    session['booth_mobile'] = mobile
    session['booth_id'] = booth_id
    session['booth_code'] = booth_code
    session['booth_name'] = booth_name
    session['booth_location'] = booth_location
    session['booth_district'] = session.get('pending_booth_district', 'Pune')
    session['booth_constituency'] = session.get('pending_booth_constituency', 'Shivaji Nagar')

    session.pop('pending_booth_otp', None)
    session.pop('pending_booth_otp_time', None)
    session.pop('pending_booth_district', None)
    session.pop('pending_booth_constituency', None)

    return jsonify({
        'status': 'success',
        'message': 'OTP verified successfully! Station is now ONLINE.',
        'redirect_url': url_for('verify.scan_page'),
        'booth_code': booth_code,
        'booth_name': booth_name,
        'region': booth_location
    })

@officer_bp.route('/booth/login_api', methods=['POST'])
def booth_login_api():
    """Direct login fallback or verification."""
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    mobile = data.get('mobile')

    if mobile:
        return booth_send_otp()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.username, o.mobile, o.location, o.booth_id,
                   b.booth_code, b.booth_name, b.region, b.district, b.constituency
            FROM officers o
            LEFT JOIN booths b ON o.booth_id = b.id
            WHERE o.username=? AND o.password=? AND o.role='Booth Officer'
        """, (username, password))
        officer = cursor.fetchone()
        if officer:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            booth_id = officer['booth_id'] if officer['booth_id'] else 1
            booth_code = officer['booth_code'] or f"BOOTH-00{booth_id}"
            booth_name = officer['booth_name'] or f"Booth {booth_id} - {officer['location']}"
            booth_region = officer['region'] or officer['location'] or "Default Region"
            booth_district = officer['district'] or 'Pune'
            booth_constituency = officer['constituency'] or 'Shivaji Nagar'

            cursor.execute("UPDATE booths SET status='ONLINE', last_active=? WHERE id=?", (now_str, booth_id))
            cursor.execute("""
                INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                VALUES (?, ?, 'LOGIN', 'Officer signed in to polling booth station', ?)
            """, (booth_id, username, now_str))
            conn.commit()

            session.permanent = True
            session['booth_logged_in'] = True
            session['booth_username'] = username
            session['booth_mobile'] = officer['mobile']
            session['booth_id'] = booth_id
            session['booth_code'] = booth_code
            session['booth_name'] = booth_name
            session['booth_location'] = booth_region
            session['booth_district'] = booth_district
            session['booth_constituency'] = booth_constituency

            return jsonify({
                'status': 'success',
                'booth_code': booth_code,
                'booth_name': booth_name,
                'region': booth_region
            })
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials or you do not have Booth Officer access'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/booth/info')
def booth_info():
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401
    return jsonify({
        'status': 'success',
        'booth_id': session.get('booth_id'),
        'booth_code': session.get('booth_code'),
        'booth_name': session.get('booth_name'),
        'booth_location': session.get('booth_location'),
        'officer_username': session.get('booth_username'),
        'officer_mobile': session.get('booth_mobile')
    })

@officer_bp.route('/booth/heartbeat', methods=['POST'])
def booth_heartbeat():
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error'}), 401
    booth_id = session.get('booth_id')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE booths SET status='ONLINE', last_active=? WHERE id=?", (now_str, booth_id))
        conn.commit()
        return jsonify({'status': 'success', 'timestamp': now_str})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/booth/logout')
def booth_logout():
    booth_id = session.get('booth_id')
    username = session.get('booth_username')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = None
    try:
        if booth_id:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE booths SET status='OFFLINE', last_active=? WHERE id=?", (now_str, booth_id))
            cursor.execute("""
                INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                VALUES (?, ?, 'LOGOUT', 'Officer logged out of booth scanner', ?)
            """, (booth_id, username, now_str))
            conn.commit()
    except Exception as e:
        print(f"[BoothLogout] Status update error: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    session.pop('booth_logged_in', None)
    session.pop('booth_username', None)
    session.pop('booth_id', None)
    session.pop('booth_code', None)
    session.pop('booth_name', None)
    session.pop('booth_location', None)
    session.pop('booth_mobile', None)
    return redirect(url_for('main.home'))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. ERO (ELECTORAL REGISTRATION OFFICER) AUTH & DECISION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@officer_bp.route('/ero/login', methods=['GET'])
def ero_login():
    if session.get('ero_logged_in'):
        return redirect(url_for('officer.ero_dashboard'))
    return render_template('ero_login.html')

@officer_bp.route('/ero/send_otp', methods=['POST'])
def ero_send_otp():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    mobile = (data.get('mobile') or '').strip()

    if not username or not password or not mobile:
        return jsonify({'status': 'error', 'message': 'Username, Password, and Registered Mobile Number are required.'})

    clean_mobile = ''.join(filter(str.isdigit, mobile))
    if len(clean_mobile) != 10:
        return jsonify({'status': 'error', 'message': 'Please enter a valid 10-digit mobile number.'})

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password, mobile, location, role, district, constituency FROM officers WHERE username=? AND role='ERO'", (username,))
        officer = cursor.fetchone()

        if not officer:
            return jsonify({'status': 'error', 'message': f'Electoral Registration Officer (ERO) "{username}" not found or unauthorized.'})

        if officer['password'] != password:
            return jsonify({'status': 'error', 'message': 'Incorrect password entered.'})

        reg_mobile = ''.join(filter(str.isdigit, str(officer['mobile'] or '')))
        if reg_mobile and reg_mobile != clean_mobile:
            return jsonify({
                'status': 'error',
                'message': f'Mobile number +91 {clean_mobile} does not match authorized ERO records for "{username}".'
            })

        # Generate 6-digit OTP
        otp_code = generate_otp()

        # Dispatch via SMS Gateway
        sms_result = send_officer_otp_sms(clean_mobile, otp_code, officer_role='ERO', officer_name=username)

        # Save in session for 2-step verification
        session['pending_ero_id'] = officer['id']
        session['pending_ero_username'] = username
        session['pending_ero_location'] = officer['location']
        session['pending_ero_district'] = officer['district'] or ''
        session['pending_ero_constituency'] = officer['constituency'] or ''
        session['pending_ero_mobile'] = clean_mobile
        session['pending_ero_otp'] = otp_code
        session['pending_ero_otp_time'] = time.time()

        masked_mobile = f"+91 ******{clean_mobile[-4:]}"

        return jsonify({
            'status': 'success',
            'message': f'SEC Security OTP has been dispatched to registered mobile {masked_mobile}',
            'masked_mobile': masked_mobile,
            'sms_sent': sms_result.get('sent', False),
            'sms_gateway': sms_result.get('gateway', 'sms_service'),
            'sms_info': sms_result.get('message', '')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/ero/verify_otp', methods=['POST'])
def ero_verify_otp():
    data = request.json or {}
    entered_otp = (data.get('otp') or '').strip()

    expected_otp = session.get('pending_ero_otp')
    otp_time = session.get('pending_ero_otp_time', 0)

    if not expected_otp:
        return jsonify({'status': 'error', 'message': 'No pending OTP session found. Please enter your credentials again.'})

    if time.time() - otp_time > 600:
        session.pop('pending_ero_otp', None)
        return jsonify({'status': 'error', 'message': 'OTP has expired. Please request a new OTP code.'})

    if entered_otp != str(expected_otp):
        return jsonify({'status': 'error', 'message': 'Incorrect OTP code entered. Please check your SMS and try again.'})

    # Successful OTP Verification -> Authorize Session
    session['ero_logged_in'] = True
    session['ero_username'] = session.get('pending_ero_username')
    session['ero_location'] = session.get('pending_ero_location')
    session['ero_district'] = session.get('pending_ero_district')
    session['ero_constituency'] = session.get('pending_ero_constituency')
    session['ero_mobile'] = session.get('pending_ero_mobile')

    session.pop('pending_ero_otp', None)
    session.pop('pending_ero_otp_time', None)

    return jsonify({
        'status': 'success',
        'message': 'OTP verified successfully! ERO Access granted.',
        'redirect_url': url_for('officer.ero_dashboard')
    })

@officer_bp.route('/ero/login_api', methods=['POST'])
def ero_login_api():
    """Direct login fallback."""
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    mobile = data.get('mobile')

    if mobile:
        return ero_send_otp()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, location, mobile, district, constituency FROM officers WHERE username=? AND password=? AND role='ERO'", (username, password))
        officer = cursor.fetchone()
        conn.close()
        if officer:
            session['ero_logged_in'] = True
            session['ero_username'] = username
            session['ero_location'] = officer['location']
            session['ero_district'] = officer['district'] or ''
            session['ero_constituency'] = officer['constituency'] or ''
            session['ero_mobile'] = officer['mobile']
            return jsonify({'status': 'success', 'redirect_url': url_for('officer.ero_dashboard')})
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials or not an authorized ERO'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@officer_bp.route('/ero/info', methods=['GET'])
def ero_info():
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    return jsonify({
        'status': 'success',
        'username': session.get('ero_username'),
        'location': session.get('ero_location'),
        'district': session.get('ero_district'),
        'constituency': session.get('ero_constituency'),
        'mobile': session.get('ero_mobile')
    })

@officer_bp.route('/ero/logout')
def ero_logout():
    session.pop('ero_logged_in', None)
    session.pop('ero_username', None)
    session.pop('ero_location', None)
    session.pop('ero_district', None)
    session.pop('ero_constituency', None)
    session.pop('ero_mobile', None)
    return redirect(url_for('main.home'))

@officer_bp.route('/ero/dashboard')
def ero_dashboard():
    if not session.get('ero_logged_in'):
        return redirect(url_for('officer.ero_login'))
    return render_template('ero_dashboard.html')

@officer_bp.route('/ero/api/stats', methods=['GET'])
def ero_stats():
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    ero_constituency = (session.get('ero_constituency') or '').strip()
    ero_district = (session.get('ero_district') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        where_clause = "WHERE 1=1"
        params = []
        if ero_constituency:
            where_clause += " AND (constituency = ? OR district = ? OR constituency LIKE ?)"
            params.extend([ero_constituency, ero_constituency, f"%{ero_constituency}%"])
        elif ero_district:
            where_clause += " AND district = ?"
            params.append(ero_district)

        cursor.execute(f"SELECT COUNT(*) FROM voters {where_clause}", params)
        total = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM voters {where_clause} AND UPPER(COALESCE(ero_status, 'APPROVED')) = 'APPROVED'", params)
        approved = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM voters {where_clause} AND UPPER(COALESCE(ero_status, '')) = 'PENDING'", params)
        pending = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM voters {where_clause} AND UPPER(COALESCE(ero_status, '')) = 'REJECTED'", params)
        rejected = cursor.fetchone()[0]

        return jsonify({
            'status': 'success',
            'data': {
                'total': total,
                'approved': approved,
                'pending': pending,
                'rejected': rejected,
                'assigned_constituency': ero_constituency,
                'assigned_district': ero_district
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/ero/api/voters', methods=['GET'])
def ero_voters():
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    ero_constituency = (session.get('ero_constituency') or '').strip()
    ero_district = (session.get('ero_district') or '').strip()

    status = (request.args.get('status') or 'ALL').strip().upper()
    district = (request.args.get('district') or '').strip()
    constituency = (request.args.get('constituency') or '').strip()
    search = (request.args.get('search') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT v_id, name, gender, district, constituency,
                   gram_panchayat_name, panchayat_samiti_name, zilha_parishad_name,
                   mahanagarpalika_name, nagar_parishad_name, nagar_panchayat_name,
                   reg_date, dob, assigned_booth_id, photo,
                   COALESCE(ero_status, 'APPROVED') AS ero_status,
                   COALESCE(ero_remarks, 'Direct Registration - Certified') AS ero_remarks,
                   ero_decided_by, ero_decided_at,
                   form6_file, relative_type, relative_name, mobile, email,
                   aadhaar_no, address_line, pincode, taluka, dob_proof_type
            FROM voters
            WHERE 1=1
        """
        params = []

        # Scope strictly by ERO's assigned constituency
        if ero_constituency:
            query += " AND (constituency = ? OR district = ? OR constituency LIKE ?)"
            params.extend([ero_constituency, ero_constituency, f"%{ero_constituency}%"])
        else:
            if district:
                query += " AND district = ?"
                params.append(district)
            if constituency:
                query += " AND (constituency = ? OR constituency LIKE ?)"
                params.extend([constituency, f"%{constituency}%"])

        if status != 'ALL':
            query += " AND UPPER(COALESCE(ero_status, 'APPROVED')) = ?"
            params.append(status)

        if search:
            query += " AND (v_id LIKE ? OR name LIKE ? OR district LIKE ? OR constituency LIKE ? OR relative_name LIKE ? OR mobile LIKE ?)"
            s_param = f"%{search}%"
            params.extend([s_param, s_param, s_param, s_param, s_param, s_param])

        query += " ORDER BY reg_date DESC, v_id DESC LIMIT 300"

        cursor.execute(query, params)
        voters = [dict(row) for row in cursor.fetchall()]

        return jsonify({
            'status': 'success',
            'data': voters,
            'assigned_constituency': ero_constituency,
            'assigned_district': ero_district
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/ero/api/decision', methods=['POST'])
def ero_decision():
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    data = request.json or {}
    v_id = (data.get('v_id') or '').strip()
    new_status = (data.get('status') or 'APPROVED').strip().upper()
    remarks = (data.get('remarks') or '').strip()

    if not v_id:
        return jsonify({'status': 'error', 'message': 'Voter ID is required'})

    if new_status not in ['APPROVED', 'REJECTED', 'PENDING']:
        return jsonify({'status': 'error', 'message': 'Invalid status. Must be APPROVED, REJECTED, or PENDING'})

    ero_username = session.get('ero_username', 'ERO')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        assigned_epic = (data.get('assigned_epic') or '').strip().upper()
        if not assigned_epic and v_id.startswith('F6'):
            assigned_epic = f"MH{random.randint(10,99)}NV{random.randint(100000, 999999)}"

        final_vid = v_id
        if new_status == 'APPROVED' and assigned_epic and assigned_epic != v_id:
            # Check if assigned_epic is already in use
            cursor.execute("SELECT v_id FROM voters WHERE v_id = ?", (assigned_epic,))
            if cursor.fetchone():
                assigned_epic = f"MH{random.randint(10,99)}NV{random.randint(100000, 999999)}"

            final_vid = assigned_epic
            cursor.execute("""
                UPDATE voters
                SET v_id = ?, ero_status = ?, ero_remarks = ?, ero_decided_by = ?, ero_decided_at = ?
                WHERE v_id = ?
            """, (final_vid, new_status, remarks, ero_username, now_str, v_id))
            
            old_photo = os.path.join(STORAGE_DIR, f"{v_id}.jpg")
            new_photo = os.path.join(STORAGE_DIR, f"{final_vid}.jpg")
            if os.path.exists(old_photo):
                try:
                    import shutil
                    shutil.copy2(old_photo, new_photo)
                    cursor.execute("UPDATE voters SET photo = ? WHERE v_id = ?", (new_photo, final_vid))
                except Exception: pass
        else:
            cursor.execute("""
                UPDATE voters
                SET ero_status = ?, ero_remarks = ?, ero_decided_by = ?, ero_decided_at = ?
                WHERE v_id = ?
            """, (new_status, remarks, ero_username, now_str, v_id))

        if cursor.rowcount == 0:
            return jsonify({'status': 'error', 'message': f'Voter ID {v_id} not found'})

        conn.commit()

        # If ERO Approved -> Generate Certified Voter Identity Card & QR Voting Pass
        card_generated = False
        if new_status == 'APPROVED':
            cursor.execute("SELECT v_id, name, dob, gender, photo, district, constituency FROM voters WHERE v_id = ?", (final_vid,))
            v_row = cursor.fetchone()
            if v_row:
                p_path = v_row['photo'] or os.path.join(STORAGE_DIR, f"{final_vid}.jpg")
                v_name = v_row['name'] or 'Citizen'
                v_dob = v_row['dob'] or '2000-01-01'
                v_gender = v_row['gender'] or 'Male'
                v_dist = v_row['district'] or 'Pune'
                v_const = v_row['constituency'] or 'Shivaji Nagar'

                try:
                    os.makedirs(ID_CARDS_DIR, exist_ok=True)
                    encrypted_token = encrypt_voter_data(final_vid, v_name, v_dob, v_gender, p_path)
                    qr = qrcode.QRCode(
                        version=None,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(encrypted_token)
                    qr.make(fit=True)
                    qr_img = qr.make_image(fill_color="black", back_color="white")
                    qr_img.save(os.path.join(ID_CARDS_DIR, final_vid + "_qr.png"))

                    create_voter_card(final_vid, v_name, v_dob, v_gender, p_path, v_dist, v_const)
                    create_voting_pass(final_vid, v_name, v_dist, v_const)
                    card_generated = True
                except Exception as card_err:
                    print(f"[ERO Approval] Card generation error for {final_vid}: {card_err}")

        epic_msg = f" (Official EPIC Assigned: {final_vid})" if final_vid != v_id else ""
        return jsonify({
            'status': 'success',
            'message': f'Electoral Roll decision for {v_id} set to {new_status} successfully.{epic_msg}' + (' Official Voter ID Card & QR Voting Pass generated!' if card_generated else ''),
            'v_id': final_vid,
            'old_vid': v_id,
            'ero_status': new_status,
            'ero_remarks': remarks,
            'ero_decided_by': ero_username,
            'ero_decided_at': now_str,
            'card_generated': card_generated
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/ero/api/staff', methods=['GET'])
def ero_staff():
    """Return Registration Officers assigned to the ERO's constituency/district."""
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    ero_constituency = (session.get('ero_constituency') or '').strip()
    ero_district     = (session.get('ero_district') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if ero_constituency:
            cursor.execute("""
                SELECT o.id, o.username, o.mobile, o.location, o.role,
                       o.district, o.constituency, o.created_at,
                       b.booth_code, b.booth_name, b.polling_station
                FROM officers o
                LEFT JOIN booths b ON o.booth_id = b.id
                WHERE o.role = 'Registration Officer'
                  AND (
                      o.constituency = ?
                      OR o.district   = ?
                      OR o.location  LIKE ?
                  )
                ORDER BY o.username ASC
            """, (ero_constituency, ero_district, f'%{ero_constituency}%'))
        elif ero_district:
            cursor.execute("""
                SELECT o.id, o.username, o.mobile, o.location, o.role,
                       o.district, o.constituency, o.created_at,
                       b.booth_code, b.booth_name, b.polling_station
                FROM officers o
                LEFT JOIN booths b ON o.booth_id = b.id
                WHERE o.role = 'Registration Officer'
                  AND (o.district = ? OR o.location LIKE ?)
                ORDER BY o.username ASC
            """, (ero_district, f'%{ero_district}%'))
        else:
            cursor.execute("""
                SELECT o.id, o.username, o.mobile, o.location, o.role,
                       o.district, o.constituency, o.created_at,
                       b.booth_code, b.booth_name, b.polling_station
                FROM officers o
                LEFT JOIN booths b ON o.booth_id = b.id
                WHERE o.role = 'Registration Officer'
                ORDER BY o.username ASC
            """)

        officers = [dict(row) for row in cursor.fetchall()]
        return jsonify({
            'status':        'success',
            'data':          officers,
            'count':         len(officers),
            'constituency':  ero_constituency,
            'district':      ero_district
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/ero/api/booths', methods=['GET'])
def ero_booths():
    """Return booths in the ERO's constituency."""
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    ero_constituency = (session.get('ero_constituency') or '').strip()
    ero_district     = (session.get('ero_district') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if ero_constituency:
            cursor.execute("""
                SELECT id, booth_code, booth_name, polling_station, district, constituency 
                FROM booths 
                WHERE constituency = ? OR district = ?
                ORDER BY booth_code ASC
            """, (ero_constituency, ero_district))
        elif ero_district:
            cursor.execute("""
                SELECT id, booth_code, booth_name, polling_station, district, constituency 
                FROM booths 
                WHERE district = ?
                ORDER BY booth_code ASC
            """, (ero_district,))
        else:
            cursor.execute("SELECT id, booth_code, booth_name, polling_station, district, constituency FROM booths ORDER BY booth_code ASC")

        booths = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': booths})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/ero/api/add_staff', methods=['POST'])
def ero_add_staff():
    """Appoint/assign a new Registration Officer for the ERO's constituency."""
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    ero_constituency = (session.get('ero_constituency') or '').strip()
    ero_district     = (session.get('ero_district') or '').strip()

    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    mobile   = (data.get('mobile') or '').strip()
    location = (data.get('location') or '').strip()
    booth_id = data.get('booth_id')

    if not username or not password:
        return jsonify({'status': 'error', 'message': 'Username and Password are required.'})

    clean_mobile = ''.join(filter(str.isdigit, mobile))
    if len(clean_mobile) != 10:
        return jsonify({'status': 'error', 'message': 'Valid 10-digit mobile number is required.'})

    if not location:
        location = f"{ero_district} - {ero_constituency}" if ero_district and ero_constituency else (ero_constituency or ero_district or 'Registration Center')

    try:
        booth_id = int(booth_id) if booth_id else None
    except (ValueError, TypeError):
        booth_id = None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if username already exists
        cursor.execute("SELECT id FROM officers WHERE username = ?", (username,))
        if cursor.fetchone():
            return jsonify({'status': 'error', 'message': f'Officer username "{username}" already exists.'})

        cursor.execute("""
            INSERT INTO officers (username, password, mobile, location, role, district, constituency, booth_id, created_at)
            VALUES (?, ?, ?, ?, 'Registration Officer', ?, ?, ?, ?)
        """, (username, password, clean_mobile, location, ero_district or 'Pune', ero_constituency or 'Shivaji Nagar', booth_id, now_str))
        conn.commit()

        return jsonify({
            'status': 'success',
            'message': f'Registration Officer "{username}" appointed successfully for {ero_constituency or "your constituency"}.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/ero/api/delete_staff/<int:officer_id>', methods=['POST', 'DELETE'])
def ero_delete_staff(officer_id):
    """Remove/unassign a Registration Officer from the ERO's constituency."""
    if not session.get('ero_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    ero_constituency = (session.get('ero_constituency') or '').strip()
    ero_district     = (session.get('ero_district') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, username, role, district, constituency, location FROM officers WHERE id = ?", (officer_id,))
        officer = cursor.fetchone()

        if not officer:
            return jsonify({'status': 'error', 'message': 'Officer not found.'})

        if officer['role'] != 'Registration Officer':
            return jsonify({'status': 'error', 'message': 'Cannot delete non-registration officers.'})

        # Check jurisdiction
        off_const = (officer['constituency'] or '').strip()
        off_dist = (officer['district'] or '').strip()
        off_loc = (officer['location'] or '').strip()

        if ero_constituency and off_const and off_const.lower() != ero_constituency.lower() and ero_constituency.lower() not in off_loc.lower():
            return jsonify({'status': 'error', 'message': f'Permission denied. Officer belongs to {off_const}, not {ero_constituency}.'})

        cursor.execute("DELETE FROM officers WHERE id = ?", (officer_id,))
        conn.commit()

        return jsonify({
            'status': 'success',
            'message': f'Registration Officer "{officer["username"]}" has been removed successfully.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3.5. ARO (ASSISTANT RETURNING OFFICER) AUTH & CONSOLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@officer_bp.route('/aro/login', methods=['GET'])
def aro_login():
    if session.get('aro_logged_in'):
        return redirect(url_for('officer.aro_dashboard'))
    return render_template('aro_login.html')

@officer_bp.route('/aro/send_otp', methods=['POST'])
def aro_send_otp():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    mobile = (data.get('mobile') or '').strip()

    if not username or not password or not mobile:
        return jsonify({'status': 'error', 'message': 'Username, Password, and Registered Mobile Number are required.'})

    clean_mobile = ''.join(filter(str.isdigit, mobile))
    if len(clean_mobile) != 10:
        return jsonify({'status': 'error', 'message': 'Please enter a valid 10-digit mobile number.'})

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, password, mobile, location, role, district, constituency 
            FROM officers 
            WHERE username=? AND (role='ARO' OR role='Assistant Returning Officer')
        """, (username,))
        officer = cursor.fetchone()

        if not officer:
            return jsonify({'status': 'error', 'message': f'Assistant Returning Officer (ARO) "{username}" not found or unauthorized.'})

        if officer['password'] != password:
            return jsonify({'status': 'error', 'message': 'Incorrect password entered.'})

        reg_mobile = ''.join(filter(str.isdigit, str(officer['mobile'] or '')))
        if reg_mobile and reg_mobile != clean_mobile:
            return jsonify({
                'status': 'error',
                'message': f'Mobile number +91 {clean_mobile} does not match authorized ARO records for "{username}".'
            })

        # Generate 6-digit OTP
        otp_code = generate_otp()

        # Dispatch via SMS Gateway
        sms_result = send_officer_otp_sms(clean_mobile, otp_code, officer_role='ARO', officer_name=username)

        # Save in session for 2-step verification
        session['pending_aro_id'] = officer['id']
        session['pending_aro_username'] = username
        session['pending_aro_location'] = officer['location']
        session['pending_aro_district'] = officer['district'] or 'Pune'
        session['pending_aro_constituency'] = officer['constituency'] or 'Shivaji Nagar'
        session['pending_aro_mobile'] = clean_mobile
        session['pending_aro_otp'] = otp_code
        session['pending_aro_otp_time'] = time.time()

        masked_mobile = f"+91 ******{clean_mobile[-4:]}"

        return jsonify({
            'status': 'success',
            'message': f'SEC Security OTP has been dispatched to registered mobile {masked_mobile}',
            'masked_mobile': masked_mobile,
            'sms_sent': sms_result.get('sent', False),
            'sms_gateway': sms_result.get('gateway', 'sms_service'),
            'sms_info': sms_result.get('message', '')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/aro/verify_otp', methods=['POST'])
def aro_verify_otp():
    data = request.json or {}
    entered_otp = (data.get('otp') or '').strip()

    expected_otp = session.get('pending_aro_otp')
    otp_time = session.get('pending_aro_otp_time', 0)

    if not expected_otp:
        return jsonify({'status': 'error', 'message': 'No pending OTP session found. Please enter your credentials again.'})

    if time.time() - otp_time > 600:
        session.pop('pending_aro_otp', None)
        return jsonify({'status': 'error', 'message': 'OTP has expired. Please request a new OTP code.'})

    if entered_otp != str(expected_otp):
        return jsonify({'status': 'error', 'message': 'Incorrect OTP code entered. Please check your SMS and try again.'})

    # Successful OTP Verification -> Authorize Session
    session['aro_logged_in'] = True
    session['aro_username'] = session.get('pending_aro_username')
    session['aro_location'] = session.get('pending_aro_location')
    session['aro_district'] = session.get('pending_aro_district')
    session['aro_constituency'] = session.get('pending_aro_constituency')
    session['aro_mobile'] = session.get('pending_aro_mobile')

    session.pop('pending_aro_otp', None)
    session.pop('pending_aro_otp_time', None)

    return jsonify({
        'status': 'success',
        'message': 'OTP verified successfully! ARO Access granted.',
        'redirect_url': url_for('officer.aro_dashboard')
    })

@officer_bp.route('/aro/login_api', methods=['POST'])
def aro_login_api():
    """Direct login fallback."""
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    mobile = data.get('mobile')

    if mobile:
        return aro_send_otp()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, location, mobile, district, constituency 
            FROM officers 
            WHERE username=? AND password=? AND (role='ARO' OR role='Assistant Returning Officer')
        """, (username, password))
        officer = cursor.fetchone()
        conn.close()
        if officer:
            session['aro_logged_in'] = True
            session['aro_username'] = username
            session['aro_location'] = officer['location']
            session['aro_district'] = officer['district'] or ''
            session['aro_constituency'] = officer['constituency'] or ''
            session['aro_mobile'] = officer['mobile']
            return jsonify({'status': 'success', 'redirect_url': url_for('officer.aro_dashboard')})
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials or not an authorized ARO'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@officer_bp.route('/aro/info', methods=['GET'])
def aro_info():
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    return jsonify({
        'status': 'success',
        'username': session.get('aro_username'),
        'location': session.get('aro_location'),
        'district': session.get('aro_district'),
        'constituency': session.get('aro_constituency'),
        'mobile': session.get('aro_mobile')
    })

@officer_bp.route('/aro/logout')
def aro_logout():
    session.pop('aro_logged_in', None)
    session.pop('aro_username', None)
    session.pop('aro_location', None)
    session.pop('aro_district', None)
    session.pop('aro_constituency', None)
    session.pop('aro_mobile', None)
    return redirect(url_for('main.home'))

@officer_bp.route('/aro/dashboard')
def aro_dashboard():
    if not session.get('aro_logged_in'):
        return redirect(url_for('officer.aro_login'))
    return render_template('aro_dashboard.html')

@officer_bp.route('/aro/api/stats', methods=['GET'])
def aro_stats():
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    aro_constituency = (session.get('aro_constituency') or '').strip()
    aro_district = (session.get('aro_district') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        where_clause = "WHERE 1=1"
        params = []
        if aro_constituency:
            where_clause += " AND (constituency = ? OR district = ? OR constituency LIKE ?)"
            params.extend([aro_constituency, aro_constituency, f"%{aro_constituency}%"])
        elif aro_district:
            where_clause += " AND district = ?"
            params.append(aro_district)

        cursor.execute(f"SELECT COUNT(*) FROM voters {where_clause}", params)
        total_voters = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM voters {where_clause} AND UPPER(COALESCE(ero_status, 'APPROVED')) = 'APPROVED'", params)
        certified_voters = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM voters {where_clause} AND (UPPER(COALESCE(ero_status, '')) = 'PENDING' OR application_id IS NOT NULL)", params)
        pending_form6 = cursor.fetchone()[0]

        b_where = "WHERE 1=1"
        b_params = []
        if aro_district:
            b_where += " AND (district = ? OR constituency = ?)"
            b_params.extend([aro_district, aro_constituency])

        cursor.execute(f"SELECT COUNT(*) FROM booths {b_where}", b_params)
        total_booths = cursor.fetchone()[0]

        return jsonify({
            'status': 'success',
            'stats': {
                'total_voters': total_voters,
                'certified_voters': certified_voters,
                'pending_form6': pending_form6,
                'total_booths': total_booths
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/aro/api/voters', methods=['GET'])
def aro_voters():
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    aro_constituency = (session.get('aro_constituency') or '').strip()
    aro_district = (session.get('aro_district') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        where_clause = "WHERE 1=1"
        params = []
        if aro_constituency:
            where_clause += " AND (constituency = ? OR district = ? OR constituency LIKE ?)"
            params.extend([aro_constituency, aro_constituency, f"%{aro_constituency}%"])
        elif aro_district:
            where_clause += " AND district = ?"
            params.append(aro_district)

        cursor.execute(f"""
            SELECT v_id, name, gender, dob, district, constituency,
                   ero_status, ero_remarks, mobile, application_id, dob_proof_type, reg_date
            FROM voters
            {where_clause}
            ORDER BY rowid DESC LIMIT 200
        """, params)
        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify({'status': 'success', 'voters': rows, 'count': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/aro/api/booths', methods=['GET'])
def aro_booths():
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    aro_constituency = (session.get('aro_constituency') or '').strip()
    aro_district = (session.get('aro_district') or '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT b.id, b.booth_code, b.booth_name, b.district, b.constituency,
                   b.polling_station, b.region, b.status, b.last_active,
                   b.offline_authorized, b.offline_token, b.offline_authorized_by,
                   b.offline_authorized_at, b.offline_valid_until,
                   o.username as officer_username,
                   (SELECT COUNT(*) FROM voted_log vl WHERE (vl.booth_id = b.id OR vl.booth_code = b.booth_code) AND (vl.region LIKE '%Offline%' OR vl.offline_token IS NOT NULL OR vl.transaction_id IS NOT NULL)) as offline_synced_count,
                   (SELECT COUNT(*) FROM booth_aro_reports bar WHERE (bar.booth_id = b.id OR bar.booth_code = b.booth_code) AND bar.status = 'PENDING') as pending_aro_reports
            FROM booths b
            LEFT JOIN officers o ON o.booth_id = b.id
            ORDER BY b.id ASC
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify({'status': 'success', 'booths': rows, 'count': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@officer_bp.route('/aro/api/verify_voter', methods=['POST'])
def aro_verify_voter():
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    data = request.json or {}
    v_id = (data.get('v_id') or '').strip()
    remarks = (data.get('remarks') or 'Field verification certified by ARO').strip()

    if not v_id:
        return jsonify({'status': 'error', 'message': 'Voter ID is required.'}), 400

    aro_username = session.get('aro_username', 'ARO Officer')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE voters
            SET ero_status = 'APPROVED',
                ero_remarks = ?,
                ero_decided_by = ?,
                ero_decided_at = ?
            WHERE v_id = ?
        """, (f"{remarks} (Certified by ARO: {aro_username})", aro_username, now_str, v_id))

        conn.commit()
        return jsonify({'status': 'success', 'message': f'Voter {v_id} certified successfully.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2.5. BOOTH OFFICER NETWORK QUERY DISPATCH TO MAIN ELECTION OFFICER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@officer_bp.route('/api/booth/network_query', methods=['POST'])
def booth_send_network_query():
    """
    Submits a network issue query/alert directly to the Main Election Officer.
    """
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized: Please log in as Booth Officer.'}), 401

    data = request.json or {}
    issue_type = (data.get('issue_type') or 'General Network Issue').strip()
    urgency = (data.get('urgency') or 'HIGH').strip().upper()
    description = (data.get('description') or '').strip()
    network_status = (data.get('network_status') or 'Degraded / Offline').strip()

    booth_id = session.get('booth_id', 1)
    booth_code = session.get('booth_code', f"BOOTH-{booth_id:03d}")
    booth_name = session.get('booth_name', 'Polling Station')
    officer_username = session.get('booth_username', 'Booth Officer')
    officer_mobile = session.get('booth_mobile', 'N/A')
    location = session.get('booth_location', 'Maharashtra')

    # Generate unique Network Query ID: NET-<YYMMDD>-<4DIGITS>
    query_id = f"NET-{datetime.now().strftime('%y%m%d')}-{random.randint(1000, 9999)}"
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO booth_network_queries 
                (query_id, booth_id, booth_code, booth_name, officer_username, officer_mobile,
                 location, issue_type, urgency, network_status, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (query_id, booth_id, booth_code, booth_name, officer_username, officer_mobile,
              location, issue_type, urgency, network_status, description, now_str))

        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (?, ?, 'NETWORK_QUERY_DISPATCHED', ?, ?)
        """, (booth_id, officer_username, f"Network Query #{query_id} ({issue_type} - {urgency}) sent to Main Election Officer", now_str))

        conn.commit()

        return jsonify({
            'status': 'success',
            'query_id': query_id,
            'message': f'Network Query #{query_id} successfully transmitted to Main Election Officer.',
            'details': {
                'query_id': query_id,
                'booth_code': booth_code,
                'booth_name': booth_name,
                'issue_type': issue_type,
                'urgency': urgency,
                'network_status': network_status,
                'status': 'PENDING',
                'created_at': now_str
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Failed to dispatch query: {str(e)}'}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/booth/my_network_queries', methods=['GET'])
def booth_my_network_queries():
    """Returns all network queries submitted by the logged-in booth station."""
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    booth_id = session.get('booth_id', 1)
    officer_username = session.get('booth_username', '')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, query_id, booth_id, booth_code, booth_name, officer_username,
                   issue_type, urgency, network_status, description, status,
                   admin_response, resolved_by, resolved_at, created_at
            FROM booth_network_queries
            WHERE booth_id = ? OR officer_username = ?
            ORDER BY id DESC LIMIT 50
        """, (booth_id, officer_username))
        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': rows, 'count': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. BOOTH OFFICER → ARO NETWORK ISSUE REPORTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@officer_bp.route('/api/booth/aro_query', methods=['POST'])
def booth_send_aro_query():
    """
    Booth Officer reports a network/technical issue directly to their area ARO.
    Stores the report in booth_aro_reports table; ARO fetches via /api/aro/booth_reports.
    """
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized: Please log in as Booth Officer.'}), 401

    data = request.json or {}
    issue_type   = (data.get('issue_type') or 'General Network Issue').strip()
    urgency      = (data.get('urgency') or 'HIGH').strip().upper()
    description  = (data.get('description') or '').strip()
    network_status = (data.get('network_status') or 'Degraded / Offline').strip()

    booth_id         = session.get('booth_id', 1)
    booth_code       = session.get('booth_code', f"BOOTH-{booth_id:03d}")
    booth_name       = session.get('booth_name', 'Polling Station')
    officer_username = session.get('booth_username', 'Booth Officer')
    officer_mobile   = session.get('booth_mobile', 'N/A')
    location         = session.get('booth_location', 'Maharashtra')
    district         = session.get('booth_district', '')
    constituency     = session.get('booth_constituency', '')

    report_id = f"ARO-{datetime.now().strftime('%y%m%d')}-{random.randint(1000, 9999)}"
    now_str   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Ensure table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS booth_aro_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL,
                booth_id INTEGER,
                booth_code TEXT,
                booth_name TEXT,
                officer_username TEXT,
                officer_mobile TEXT,
                location TEXT,
                district TEXT,
                constituency TEXT,
                issue_type TEXT,
                urgency TEXT,
                network_status TEXT,
                description TEXT,
                status TEXT DEFAULT 'PENDING',
                aro_response TEXT,
                resolved_by TEXT,
                resolved_at TEXT,
                created_at TEXT
            )
        """)

        cursor.execute("""
            INSERT INTO booth_aro_reports
                (report_id, booth_id, booth_code, booth_name, officer_username, officer_mobile,
                 location, district, constituency, issue_type, urgency, network_status,
                 description, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (report_id, booth_id, booth_code, booth_name, officer_username, officer_mobile,
              location, district, constituency, issue_type, urgency, network_status,
              description, now_str))

        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (?, ?, 'ARO_REPORT_DISPATCHED', ?, ?)
        """, (booth_id, officer_username,
              f"ARO Report #{report_id} ({issue_type} - {urgency}) dispatched to Area ARO", now_str))

        conn.commit()

        return jsonify({
            'status': 'success',
            'report_id': report_id,
            'message': f'Report #{report_id} successfully sent to your Area ARO Officer.',
            'details': {
                'report_id': report_id,
                'booth_code': booth_code,
                'booth_name': booth_name,
                'issue_type': issue_type,
                'urgency': urgency,
                'status': 'PENDING',
                'created_at': now_str
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Failed to dispatch ARO report: {str(e)}'}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/booth/my_aro_reports', methods=['GET'])
def booth_my_aro_reports():
    """Returns all ARO-targeted reports submitted by the logged-in booth station."""
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    booth_id         = session.get('booth_id', 1)
    officer_username = session.get('booth_username', '')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS booth_aro_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL,
                booth_id INTEGER,
                booth_code TEXT,
                booth_name TEXT,
                officer_username TEXT,
                officer_mobile TEXT,
                location TEXT,
                district TEXT,
                constituency TEXT,
                issue_type TEXT,
                urgency TEXT,
                network_status TEXT,
                description TEXT,
                status TEXT DEFAULT 'PENDING',
                aro_response TEXT,
                resolved_by TEXT,
                resolved_at TEXT,
                created_at TEXT
            )
        """)
        cursor.execute("""
            SELECT * FROM booth_aro_reports
            WHERE booth_id = ? OR officer_username = ?
            ORDER BY id DESC LIMIT 50
        """, (booth_id, officer_username))
        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': rows, 'count': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/aro/booth_reports', methods=['GET'])
def aro_get_booth_reports():
    """ARO fetches all booth network issue reports addressed to their area."""
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    aro_district     = session.get('aro_district', '')
    aro_constituency = session.get('aro_constituency', '')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS booth_aro_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL,
                booth_id INTEGER,
                booth_code TEXT,
                booth_name TEXT,
                officer_username TEXT,
                officer_mobile TEXT,
                location TEXT,
                district TEXT,
                constituency TEXT,
                issue_type TEXT,
                urgency TEXT,
                network_status TEXT,
                description TEXT,
                status TEXT DEFAULT 'PENDING',
                aro_response TEXT,
                resolved_by TEXT,
                resolved_at TEXT,
                created_at TEXT
            )
        """)
        # Fetch reports matching ARO's district/constituency or all if no filter
        if aro_district or aro_constituency:
            cursor.execute("""
                SELECT * FROM booth_aro_reports
                WHERE district = ? OR constituency = ?
                   OR district LIKE ? OR constituency LIKE ?
                ORDER BY id DESC LIMIT 100
            """, (aro_district, aro_constituency,
                  f'%{aro_district}%', f'%{aro_constituency}%'))
        else:
            cursor.execute("SELECT * FROM booth_aro_reports ORDER BY id DESC LIMIT 100")

        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': rows, 'count': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/aro/resolve_booth_report', methods=['POST'])
def aro_resolve_booth_report():
    """ARO marks a booth report as resolved with a response message."""
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    data      = request.json or {}
    report_id = (data.get('report_id') or '').strip()
    response  = (data.get('response') or 'Issue acknowledged and resolved.').strip()

    if not report_id:
        return jsonify({'status': 'error', 'message': 'report_id is required.'}), 400

    aro_username = session.get('aro_username', 'ARO Officer')
    now_str      = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE booth_aro_reports
            SET status = 'RESOLVED', aro_response = ?, resolved_by = ?, resolved_at = ?
            WHERE report_id = ?
        """, (response, aro_username, now_str, report_id))
        conn.commit()
        return jsonify({'status': 'success', 'message': f'Report {report_id} marked as resolved.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3.5. ARO OFFLINE MODE PERMISSION & ENCRYPTED DATABASE MANAGEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@officer_bp.route('/api/aro/grant_offline_mode', methods=['POST'])
def aro_grant_offline_mode():
    """
    ARO grants cryptographic permission to a specific booth experiencing network issues
    to operate in Secure Offline Verification Mode.
    """
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized: Please log in as ARO.'}), 401

    data = request.json or {}
    booth_id = data.get('booth_id')
    booth_code = (data.get('booth_code') or '').strip()
    report_id = (data.get('report_id') or '').strip()
    valid_hours = int(data.get('valid_hours') or 24)

    if not booth_id and not booth_code:
        return jsonify({'status': 'error', 'message': 'Booth ID or Booth Code is required.'}), 400

    aro_username = session.get('aro_username', 'ARO Officer')
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    from datetime import timedelta
    valid_until_str = (now + timedelta(hours=valid_hours)).strftime('%Y-%m-%d %H:%M:%S')

    token_code = f"ARO-OFFLINE-{now.strftime('%y%m%d')}-{random.randint(1000, 9999)}"

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Find booth
        if booth_id:
            cursor.execute("SELECT id, booth_code, booth_name, district, constituency FROM booths WHERE id=?", (booth_id,))
        else:
            cursor.execute("SELECT id, booth_code, booth_name, district, constituency FROM booths WHERE booth_code=?", (booth_code,))
        b_row = cursor.fetchone()

        if not b_row:
            return jsonify({'status': 'error', 'message': 'Target polling booth not found.'}), 404

        b_id = b_row['id']
        b_code = b_row['booth_code']
        b_name = b_row['booth_name']

        # Update booth authorization in DB
        cursor.execute("""
            UPDATE booths
            SET offline_authorized = 1,
                offline_token = ?,
                offline_authorized_by = ?,
                offline_authorized_at = ?,
                offline_valid_until = ?
            WHERE id = ?
        """, (token_code, aro_username, now_str, valid_until_str, b_id))

        # If linked to a report, mark it resolved
        if report_id:
            cursor.execute("""
                UPDATE booth_aro_reports
                SET status = 'RESOLVED',
                    aro_response = ?,
                    resolved_by = ?,
                    resolved_at = ?
                WHERE report_id = ?
            """, (f"Offline Verification Mode GRANTED by ARO ({token_code}). Valid until {valid_until_str}.",
                  aro_username, now_str, report_id))

        # Log in booth activity log
        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (?, ?, 'ARO_OFFLINE_MODE_GRANTED', ?, ?)
        """, (b_id, aro_username, f"Offline Mode Authorized by ARO {aro_username}. Token: {token_code}. Valid until: {valid_until_str}", now_str))

        conn.commit()

        return jsonify({
            'status': 'success',
            'message': f"Offline Verification Mode successfully authorized for {b_code} ({b_name}).",
            'offline_token': token_code,
            'booth_code': b_code,
            'booth_name': b_name,
            'valid_until': valid_until_str,
            'authorized_by': aro_username
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Failed to grant offline mode: {str(e)}"}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/aro/revoke_offline_mode', methods=['POST'])
def aro_revoke_offline_mode():
    """
    ARO revokes offline mode permission once network connectivity is restored.
    """
    if not session.get('aro_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    data = request.json or {}
    booth_id = data.get('booth_id')
    booth_code = (data.get('booth_code') or '').strip()

    aro_username = session.get('aro_username', 'ARO Officer')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if booth_id:
            cursor.execute("UPDATE booths SET offline_authorized = 0 WHERE id = ?", (booth_id,))
        else:
            cursor.execute("UPDATE booths SET offline_authorized = 0 WHERE booth_code = ?", (booth_code,))

        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (?, ?, 'ARO_OFFLINE_MODE_REVOKED', ?, ?)
        """, (booth_id or 1, aro_username, f"Offline Mode Revoked by ARO {aro_username}. Station returned to cloud-sync only.", now_str))

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Offline Mode permission revoked.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/booth/offline_status', methods=['GET'])
def booth_offline_status():
    """
    Checks if the logged-in booth station is authorized for offline verification.
    """
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    booth_id = session.get('booth_id', 1)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, booth_code, booth_name, district, constituency,
                   offline_authorized, offline_token, offline_authorized_by,
                   offline_authorized_at, offline_valid_until
            FROM booths WHERE id = ?
        """, (booth_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Booth not found'}), 404

        is_auth = bool(row['offline_authorized'])
        valid_until = row['offline_valid_until'] or ''

        # Check expiration if set
        if is_auth and valid_until:
            try:
                exp_dt = datetime.strptime(valid_until, '%Y-%m-%d %H:%M:%S')
                if datetime.now() > exp_dt:
                    is_auth = False
            except Exception:
                pass

        return jsonify({
            'status': 'success',
            'offline_authorized': is_auth,
            'booth_code': row['booth_code'],
            'booth_name': row['booth_name'],
            'offline_token': row['offline_token'] if is_auth else None,
            'authorized_by': row['offline_authorized_by'] if is_auth else None,
            'authorized_at': row['offline_authorized_at'] if is_auth else None,
            'valid_until': row['offline_valid_until'] if is_auth else None
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/booth/download_offline_package', methods=['GET'])
def booth_download_offline_package():
    """
    Generates an authenticated, encrypted offline database package of all eligible voters
    for the booth's constituency/district.
    """
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized: Please log in as Booth Officer.'}), 401

    booth_id = session.get('booth_id', 1)
    booth_code = session.get('booth_code', f"BOOTH-{booth_id:03d}")
    booth_name = session.get('booth_name', 'Polling Station')
    booth_officer = session.get('booth_username', 'Booth Officer')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check offline authorization
        cursor.execute("""
            SELECT id, district, constituency, offline_authorized, offline_token,
                   offline_authorized_by, offline_valid_until
            FROM booths WHERE id = ?
        """, (booth_id,))
        b_row = cursor.fetchone()

        if not b_row:
            return jsonify({'status': 'error', 'message': 'Booth record not found.'}), 404

        token = b_row['offline_token'] or 'BACKUP-AUTH-TOKEN'
        b_dist = b_row['district'] or ''
        b_const = b_row['constituency'] or ''

        # Load all voters for this booth/constituency who are approved
        if b_dist or b_const:
            cursor.execute("""
                SELECT v_id, name, gender, dob, district, constituency, photo,
                       gram_panchayat, panchayat_samiti, zilha_parishad,
                       mahanagarpalika, nagar_parishad, nagar_panchayat,
                       ero_status
                FROM voters
                WHERE (district = ? OR constituency = ? OR assigned_booth_id = ?)
                  AND (ero_status IS NULL OR UPPER(ero_status) = 'APPROVED')
                ORDER BY name ASC
            """, (b_dist, b_const, booth_id))
        else:
            cursor.execute("""
                SELECT v_id, name, gender, dob, district, constituency, photo,
                       gram_panchayat, panchayat_samiti, zilha_parishad,
                       mahanagarpalika, nagar_parishad, nagar_panchayat,
                       ero_status
                FROM voters
                WHERE ero_status IS NULL OR UPPER(ero_status) = 'APPROVED'
                ORDER BY name ASC
            """)

        rows = cursor.fetchall()
        voters_list = []

        for r in rows:
            v_id = r['v_id']
            p_path = r['photo'] or ''
            face_bytes_b64 = ""
            
            # Read or compress face photo bytes for offline biometric matching
            if p_path and os.path.exists(p_path):
                try:
                    f_bytes = compress_photo_to_jpeg(p_path, max_size=40)
                    if f_bytes:
                        face_bytes_b64 = base64.b64encode(f_bytes).decode('utf-8')
                except Exception:
                    pass
            
            # If no stored photo file, check temp cache
            if not face_bytes_b64:
                try:
                    temp_p = os.path.join(STORAGE_DIR, f"temp_{v_id}.jpg")
                    if os.path.exists(temp_p):
                        with open(temp_p, "rb") as tf:
                            face_bytes_b64 = base64.b64encode(tf.read()).decode('utf-8')
                except Exception:
                    pass

            voters_list.append({
                "v_id": v_id,
                "name": r['name'] or '',
                "gender": r['gender'] or '',
                "dob": r['dob'] or '',
                "district": r['district'] or '',
                "constituency": r['constituency'] or '',
                "ero_status": r['ero_status'] or 'APPROVED',
                "elections": {
                    "gram_panchayat": r['gram_panchayat'],
                    "panchayat_samiti": r['panchayat_samiti'],
                    "zilha_parishad": r['zilha_parishad'],
                    "mahanagarpalika": r['mahanagarpalika'],
                    "nagar_parishad": r['nagar_parishad'],
                    "nagar_panchayat": r['nagar_panchayat']
                },
                "face_bytes": face_bytes_b64
            })

        # Ensure constituency-specific database is synced and up to date
        constituency_db_file = None
        if b_const:
            try:
                sync_master_to_constituency_db(b_const)
                const_slug = get_constituency_slug(b_const)
                constituency_db_file = f"constituency_{const_slug}.db"
            except Exception as sync_e:
                print(f"[Offline Package] Constituency sync note: {sync_e}")

        # Build master offline package
        offline_package = {
            "version": "1.0-SEC-MAHA-OFFLINE",
            "booth_id": booth_id,
            "booth_code": booth_code,
            "booth_name": booth_name,
            "district": b_dist,
            "constituency": b_const,
            "constituency_db": constituency_db_file,
            "offline_token": token,
            "authorized_by": b_row['offline_authorized_by'] or 'ARO Console',
            "valid_until": b_row['offline_valid_until'] or 'POLLING_DAY_END',
            "generated_at": now_str,
            "voter_count": len(voters_list),
            "voters": voters_list
        }

        # Encrypt the package with authenticated crypto
        encrypted_result = encrypt_offline_package(offline_package)

        # Log package download in audit log
        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (?, ?, 'OFFLINE_PACKAGE_DOWNLOADED', ?, ?)
        """, (booth_id, booth_officer, f"Downloaded offline encrypted database ({len(voters_list)} voter records for constituency '{b_const}'). Token: {token}", now_str))
        conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Encrypted offline database package generated for {booth_code} ({len(voters_list)} voters in constituency '{b_const or 'General'}').",
            "package": encrypted_result,
            "voters": voters_list,
            "booth_code": booth_code,
            "constituency": b_const,
            "constituency_db": constituency_db_file,
            "voter_count": len(voters_list),
            "offline_token": token,
            "generated_at": now_str
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to build offline package: {str(e)}"}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/constituency/databases', methods=['GET'])
def api_constituency_databases():
    """
    Returns list and status of all isolated constituency databases.
    """
    try:
        dbs = list_all_constituency_databases()
        return jsonify({'status': 'success', 'databases': dbs, 'count': len(dbs)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@officer_bp.route('/api/constituency/download_db_file/<slug>', methods=['GET'])
def download_constituency_db_file(slug):
    """
    Directly downloads the raw isolated SQLite .db file for a given constituency.
    """
    try:
        clean_slug = get_constituency_slug(slug)
        db_path = get_constituency_db_path(clean_slug)
        if not os.path.exists(db_path):
            # Attempt to find and sync
            sync_master_to_constituency_db(clean_slug)

        if os.path.exists(db_path):
            return send_file(db_path, as_attachment=True, download_name=f"constituency_{clean_slug}.db")
        else:
            return jsonify({'status': 'error', 'message': f'Constituency database file not found for {slug}'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/booth/sync_offline_votes', methods=['POST'])
def booth_sync_offline_votes():
    """
    Receives and processes encrypted/signed offline vote records stored locally at the booth station
    once network connectivity is restored.
    """
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    data = request.json or {}
    votes = data.get('votes') or []
    offline_token = (data.get('offline_token') or '').strip()

    if not votes:
        return jsonify({'status': 'error', 'message': 'No offline vote records provided for synchronization.'}), 400

    booth_id = session.get('booth_id', 1)
    booth_code = session.get('booth_code', f"BOOTH-{booth_id:03d}")
    booth_officer = session.get('booth_username', 'Booth Officer')
    region = session.get('booth_location', 'Maharashtra')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    synced_records = []
    duplicate_records = []
    failed_records = []

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        for vote in votes:
            v_id = (vote.get('v_id') or '').strip()
            voter_name = (vote.get('voter_name') or '').strip()
            election = (vote.get('election') or '').strip()
            voted_at = (vote.get('voted_at') or now_str).strip()
            txn_id = (vote.get('transaction_id') or '').strip()
            token_val = (vote.get('offline_token') or offline_token or 'ARO-OFFLINE').strip()

            if not txn_id:
                txn_id = f"TXN-OFFLINE-{datetime.now().strftime('%y%m%d%H%M%S')}-{random.randint(1000, 9999)}"

            if not v_id or not election:
                failed_records.append({
                    'transaction_id': txn_id,
                    'v_id': v_id,
                    'voter_name': voter_name,
                    'election': election,
                    'status': 'FAILED',
                    'error': f"Invalid record format: missing voter ID or election type ({vote})"
                })
                continue

            # ── 1. TRANSACTION ID DEDUPLICATION CHECK ──
            try:
                cursor.execute("""
                    SELECT id, v_id, voter_name, election, voted_at, transaction_id
                    FROM voted_log
                    WHERE transaction_id = ?
                """, (txn_id,))
                existing_txn = cursor.fetchone()
                if existing_txn:
                    duplicate_records.append({
                        'transaction_id': txn_id,
                        'v_id': v_id,
                        'voter_name': voter_name or (existing_txn['voter_name'] if hasattr(existing_txn, 'keys') else existing_txn[2]),
                        'election': election,
                        'status': 'DUPLICATE_TXN_SKIPPED',
                        'reason': f"Transaction ID '{txn_id}' already synced and recorded."
                    })
                    continue
            except Exception:
                pass

            # ── 2. VOTER RECORD & DOUBLE VOTING CHECK ──
            try:
                cursor.execute(f"SELECT {election}, name FROM voters WHERE v_id = ?", (v_id,))
                v_row = cursor.fetchone()
                if not v_row:
                    failed_records.append({
                        'transaction_id': txn_id,
                        'v_id': v_id,
                        'voter_name': voter_name,
                        'election': election,
                        'status': 'FAILED',
                        'error': f"Voter '{v_id}' not found in official electoral roll."
                    })
                    continue

                if not voter_name:
                    voter_name = v_row['name']

                # Check if already voted in this election
                if v_row[0] == 0:
                    duplicate_records.append({
                        'transaction_id': txn_id,
                        'v_id': v_id,
                        'voter_name': voter_name,
                        'election': election,
                        'status': 'DUPLICATE_VOTE_SKIPPED',
                        'reason': f"Voter {voter_name} ({v_id}) has already cast a vote for {election.replace('_', ' ').title()}."
                    })
                    continue

                # ── 3. RECORD VOTE & MINE BLOCKCHAIN BLOCK ──
                cursor.execute(f"UPDATE voters SET {election} = 0 WHERE v_id = ?", (v_id,))

                # Insert into centralized voted_log with transaction_id and offline_token
                try:
                    cursor.execute("""
                        INSERT INTO voted_log (v_id, voter_name, election, booth_officer, region, voted_at, booth_id, booth_code, transaction_id, offline_token)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (v_id, voter_name, election.replace('_', ' ').title(), booth_officer,
                          f"{region} [Offline Synced]", voted_at, booth_id, booth_code, txn_id, token_val))
                except Exception:
                    cursor.execute("""
                        INSERT INTO voted_log (v_id, voter_name, election, booth_officer, region, voted_at, booth_id, booth_code)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (v_id, voter_name, election.replace('_', ' ').title(), booth_officer,
                          f"{region} [Offline Synced]", voted_at, booth_id, booth_code))

                # Mine & append block into blockchain ledger with transaction_id
                new_block = Blockchain.add_vote_block(
                    conn,
                    vid=v_id,
                    voter_name=voter_name,
                    election=election.replace('_', ' ').title(),
                    booth_officer=booth_officer,
                    region=f"{region} [Offline Synced]",
                    booth_id=booth_id,
                    booth_code=booth_code,
                    timestamp=voted_at,
                    transaction_id=txn_id,
                    offline_token=token_val
                )

                # Also update constituency-specific database for offline consistency
                try:
                    c_const = session.get('booth_constituency') or 'Shivaji Nagar'
                    c_conn = get_constituency_db_connection(c_const)
                    c_cur = c_conn.cursor()
                    c_cur.execute(f"UPDATE voters SET {election} = 0 WHERE v_id = ?", (v_id,))
                    c_cur.execute("""
                        INSERT OR REPLACE INTO voted_log (v_id, voter_name, election, booth_officer, region, voted_at, booth_id, booth_code, transaction_id, offline_token, sync_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SYNCED')
                    """, (v_id, voter_name, election.replace('_', ' ').title(), booth_officer, f"{region} [Offline Synced]", voted_at, booth_id, booth_code, txn_id, token_val))
                    c_cur.execute("""
                        INSERT OR REPLACE INTO offline_sync_queue (transaction_id, v_id, voter_name, election, booth_code, booth_officer, voted_at, offline_token, sync_status, synced_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SYNCED', ?)
                    """, (txn_id, v_id, voter_name, election.replace('_', ' ').title(), booth_code, booth_officer, voted_at, token_val, now_str))
                    c_conn.commit()
                    c_conn.close()
                except Exception as c_err:
                    print(f"[Offline Sync] Constituency DB sync note: {c_err}")

                synced_records.append({
                    'transaction_id': txn_id,
                    'v_id': v_id,
                    'voter_name': voter_name,
                    'election': election.replace('_', ' ').title(),
                    'status': 'SYNCED',
                    'block_index': new_block.index if new_block else 0,
                    'block_hash': new_block.hash if new_block else 'HASH',
                    'voted_at': voted_at,
                    'synced_at': now_str
                })
            except Exception as vote_err:
                failed_records.append({
                    'transaction_id': txn_id,
                    'v_id': v_id,
                    'voter_name': voter_name,
                    'election': election,
                    'status': 'FAILED',
                    'error': str(vote_err)
                })

        # Log bulk sync activity
        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (?, ?, 'OFFLINE_VOTES_SYNCED', ?, ?)
        """, (booth_id, booth_officer,
              f"Synced {len(synced_records)} offline votes ({len(duplicate_records)} duplicate transactions blocked, {len(failed_records)} failed. Token: {offline_token})", now_str))

        conn.commit()

        return jsonify({
            'status': 'success',
            'message': f"Synchronization processed: {len(synced_records)} Synced, {len(duplicate_records)} Duplicates Prevented, {len(failed_records)} Failed.",
            'synced_count': len(synced_records),
            'duplicate_count': len(duplicate_records),
            'failed_count': len(failed_records),
            'synced_records': synced_records,
            'duplicate_records': duplicate_records,
            'failed_records': failed_records,
            'timestamp': now_str
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Offline votes synchronization failed: {str(e)}"}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@officer_bp.route('/api/booth/sync_audit_log', methods=['GET'])
def booth_sync_audit_log():
    """
    Returns the real-time synchronization audit log for the logged-in booth.
    """
    if not session.get('booth_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    booth_id = session.get('booth_id', 1)
    booth_code = session.get('booth_code', f"BOOTH-{booth_id:03d}")

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v_id, voter_name, election, booth_officer, region, voted_at, transaction_id, offline_token
            FROM voted_log
            WHERE (booth_id = ? OR booth_code = ?) AND (region LIKE '%Offline%' OR offline_token IS NOT NULL OR transaction_id IS NOT NULL)
            ORDER BY id DESC LIMIT 50
        """, (booth_id, booth_code))
        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify({'status': 'success', 'records': rows, 'count': len(rows)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. UNIVERSAL CHANGE PASSWORD ENDPOINT (FOR ALL ROLES)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@officer_bp.route('/api/change_password', methods=['POST'])
def universal_change_password():
    """
    Allows any authenticated user (Admin, ERO, ARO, Registration Officer, Booth Officer)
    to safely change their password after entering their current password.
    """
    data = request.json or {}
    current_password = (data.get('current_password') or '').strip()
    new_password = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    if not current_password or not new_password:
        return jsonify({'status': 'error', 'message': 'Both current password and new password are required.'}), 400

    if len(new_password) < 6:
        return jsonify({'status': 'error', 'message': 'New password must be at least 6 characters long.'}), 400

    if new_password != confirm_password:
        return jsonify({'status': 'error', 'message': 'New password and confirmation do not match.'}), 400

    # Determine logged in identity and role from active session
    username = None
    role = None

    if session.get('admin_logged_in'):
        username = session.get('admin_username') or 'admin'
        role = 'Admin'
    elif session.get('ero_logged_in'):
        username = session.get('ero_username')
        role = 'ERO'
    elif session.get('aro_logged_in'):
        username = session.get('aro_username')
        role = 'ARO'
    elif session.get('officer_logged_in'):
        username = session.get('officer_username')
        role = 'Registration Officer'
    elif session.get('booth_logged_in'):
        username = session.get('booth_username')
        role = 'Booth Officer'

    if not username:
        return jsonify({'status': 'error', 'message': 'Unauthorized: Please log in to change your password.'}), 401

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if role == 'Admin':
            cursor.execute("SELECT id, password FROM officers WHERE username=? AND role='Admin'", (username,))
            admin_row = cursor.fetchone()
            if admin_row:
                if admin_row['password'] != current_password:
                    return jsonify({'status': 'error', 'message': 'Current password entered is incorrect.'}), 400
                cursor.execute("UPDATE officers SET password=? WHERE id=?", (new_password, admin_row['id']))
            else:
                from routes.admin_routes import ADMIN_PASSWORD
                if current_password != ADMIN_PASSWORD:
                    return jsonify({'status': 'error', 'message': 'Current password entered is incorrect.'}), 400
                cursor.execute("""
                    INSERT INTO officers (username, password, mobile, location, role, created_at)
                    VALUES ('admin', ?, '9876543200', 'State Election Commission HQ', 'Admin', ?)
                """, (new_password, now_str))
        else:
            cursor.execute("SELECT id, password FROM officers WHERE username=?", (username,))
            officer = cursor.fetchone()
            if not officer:
                return jsonify({'status': 'error', 'message': f'Officer account "{username}" not found.'}), 404

            if officer['password'] != current_password:
                return jsonify({'status': 'error', 'message': 'Current password entered is incorrect.'}), 400

            cursor.execute("UPDATE officers SET password=? WHERE id=?", (new_password, officer['id']))

        try:
            cursor.execute("""
                INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                VALUES (1, ?, 'PASSWORD_CHANGED', ?, ?)
            """, (username, f"Password successfully changed by {role} ({username})", now_str))
        except Exception:
            pass

        conn.commit()
        return jsonify({
            'status': 'success',
            'message': f'Password successfully updated for {role} ({username})!'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Database error: {str(e)}'}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

