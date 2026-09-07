import sqlite3
import random
import time
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from database import get_db_connection
from utils.sms_gateway import send_officer_otp_sms

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
                   b.booth_code, b.booth_name, b.region
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

        # Save in session for 2-step verification
        session['pending_booth_officer_id'] = officer['id']
        session['pending_booth_username'] = username
        session['pending_booth_mobile'] = clean_mobile
        session['pending_booth_id'] = booth_id
        session['pending_booth_code'] = booth_code
        session['pending_booth_name'] = booth_name
        session['pending_booth_location'] = booth_region
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

    session['booth_logged_in'] = True
    session['booth_username'] = username
    session['booth_mobile'] = mobile
    session['booth_id'] = booth_id
    session['booth_code'] = booth_code
    session['booth_name'] = booth_name
    session['booth_location'] = booth_location

    session.pop('pending_booth_otp', None)
    session.pop('pending_booth_otp_time', None)

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
                   b.booth_code, b.booth_name, b.region
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

            cursor.execute("UPDATE booths SET status='ONLINE', last_active=? WHERE id=?", (now_str, booth_id))
            cursor.execute("""
                INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                VALUES (?, ?, 'LOGIN', 'Officer signed in to polling booth station', ?)
            """, (booth_id, username, now_str))
            conn.commit()

            session['booth_logged_in'] = True
            session['booth_username'] = username
            session['booth_mobile'] = officer['mobile']
            session['booth_id'] = booth_id
            session['booth_code'] = booth_code
            session['booth_name'] = booth_name
            session['booth_location'] = booth_region

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
