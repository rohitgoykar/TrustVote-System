import sqlite3
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from database import get_db_connection

admin_bp = Blueprint('admin', __name__)

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'

@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in') and request.method == 'GET':
        return redirect(url_for('admin.admin_dashboard'))
    return render_template('admin_login.html')

@admin_bp.route('/admin/login_api', methods=['POST'])
def admin_login_api():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()

    valid = False
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM officers WHERE username=? AND role='Admin'", (username,))
        admin_row = cursor.fetchone()
        if admin_row:
            if admin_row['password'] == password:
                valid = True
        elif username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            valid = True
    except Exception:
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            valid = True
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    if valid:
        session['admin_logged_in'] = True
        session['admin_username'] = username or ADMIN_USERNAME
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid Main Election Officer credentials'})

@admin_bp.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin.admin_login'))

@admin_bp.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.admin_login'))
    return render_template('admin.html')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. HIERARCHICAL CASCADING OPTIONS API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/admin/hierarchy_options')
def hierarchy_options():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Elections
        cursor.execute("SELECT id, election_code, election_name, election_type, status FROM elections ORDER BY id DESC")
        elections = [dict(row) for row in cursor.fetchall()]

        # Polling Booths with full hierarchy
        cursor.execute("""
            SELECT id, booth_code, booth_name, district, constituency, polling_station, region, status, last_active
            FROM booths
            ORDER BY district ASC, constituency ASC, id ASC
        """)
        booths = [dict(row) for row in cursor.fetchall()]

        return jsonify({
            'status': 'success',
            'data': {
                'elections': elections,
                'booths': booths
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. HIERARCHICAL BOOTH DRILL-DOWN STATS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/admin/booth_drilldown_stats')
def booth_drilldown_stats():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    district = request.args.get('district', '').strip()
    constituency = request.args.get('constituency', '').strip()
    station = request.args.get('station', '').strip()
    booth_id = request.args.get('booth_id', '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Build booth ID filter clause
        booth_filter_sql = ""
        booth_params = []

        conditions = []
        if district and district != 'all':
            conditions.append("district = ?")
            booth_params.append(district)
        if constituency and constituency != 'all':
            conditions.append("constituency = ?")
            booth_params.append(constituency)
        if station and station != 'all':
            conditions.append("polling_station = ?")
            booth_params.append(station)
        if booth_id and booth_id != 'all':
            conditions.append("id = ?")
            booth_params.append(int(booth_id))

        if conditions:
            booth_filter_sql = " WHERE " + " AND ".join(conditions)

        # Get matching booth IDs
        cursor.execute(f"SELECT id, booth_code, booth_name, status FROM booths {booth_filter_sql}", tuple(booth_params))
        matching_booths = cursor.fetchall()
        matching_ids = [b['id'] for b in matching_booths]
        total_matching_booths = len(matching_ids)
        online_matching_booths = sum(1 for b in matching_booths if b['status'] == 'ONLINE')

        if not matching_ids:
            return jsonify({
                'status': 'success',
                'data': {
                    'total_voters': 0,
                    'verified': 0,
                    'rejected': 0,
                    'already_voted': 0,
                    'turnout_pct': 0.0,
                    'total_booths': 0,
                    'online_booths': 0,
                    'activities': []
                }
            })

        placeholders = ','.join('?' for _ in matching_ids)

        # 1. Total Assigned Voters in this scope
        cursor.execute(f"SELECT COUNT(*) FROM voters WHERE assigned_booth_id IN ({placeholders})", tuple(matching_ids))
        total_voters = cursor.fetchone()[0]

        # 2. Verified & Cast Votes
        cursor.execute(f"SELECT COUNT(*) FROM voted_log WHERE booth_id IN ({placeholders})", tuple(matching_ids))
        verified_votes = cursor.fetchone()[0]

        # 3. Rejected Attempts (Face mismatch / Ineligible)
        cursor.execute(f"""
            SELECT COUNT(*) FROM booth_activity_log
            WHERE booth_id IN ({placeholders}) AND action IN ('VERIFICATION_FAILED', 'REJECTED_UNKNOWN', 'NOT_REGISTERED_FOR_ELECTION', 'EXPIRED_REGISTRATION')
        """, tuple(matching_ids))
        rejected_attempts = cursor.fetchone()[0]

        # 4. Blocked Duplicate/Already Voted Attempts
        cursor.execute(f"""
            SELECT COUNT(*) FROM booth_activity_log
            WHERE booth_id IN ({placeholders}) AND action = 'ALREADY_VOTED_BLOCKED'
        """, tuple(matching_ids))
        already_voted_blocked = cursor.fetchone()[0]

        turnout_pct = round((verified_votes / total_voters * 100), 1) if total_voters > 0 else 0.0

        # 5. Live Activity Feed for this scope
        cursor.execute(f"""
            SELECT al.id, al.action, al.details, al.officer_username, al.timestamp,
                   b.booth_code, b.booth_name, b.district, b.constituency
            FROM booth_activity_log al
            LEFT JOIN booths b ON al.booth_id = b.id
            WHERE al.booth_id IN ({placeholders})
            ORDER BY al.id DESC
            LIMIT 40
        """, tuple(matching_ids))
        activities = [dict(row) for row in cursor.fetchall()]

        return jsonify({
            'status': 'success',
            'data': {
                'total_voters': total_voters,
                'verified': verified_votes,
                'rejected': rejected_attempts,
                'already_voted': already_voted_blocked,
                'turnout_pct': turnout_pct,
                'total_booths': total_matching_booths,
                'online_booths': online_matching_booths,
                'activities': activities
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. POLLING BOOTHS MATRIX
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/admin/get_booths')
def get_booths():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    district = request.args.get('district', '').strip()
    constituency = request.args.get('constituency', '').strip()
    station = request.args.get('station', '').strip()
    booth_id = request.args.get('booth_id', '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        sql = """
            SELECT b.id, b.booth_code, b.booth_name, b.district, b.constituency, b.polling_station, b.region, b.status, b.last_active,
                   (SELECT o.username FROM officers o WHERE o.booth_id = b.id AND o.role='Booth Officer' LIMIT 1) as officer_username,
                   (SELECT COUNT(*) FROM voters v WHERE v.assigned_booth_id = b.id) as assigned_voters,
                   (SELECT COUNT(*) FROM voted_log vl WHERE vl.booth_id = b.id) as votes_recorded,
                   (SELECT COUNT(DISTINCT vl2.v_id) FROM voted_log vl2 WHERE vl2.booth_id = b.id) as verified_voters
            FROM booths b
        """
        conditions = []
        params = []
        if district and district != 'all':
            conditions.append("b.district = ?")
            params.append(district)
        if constituency and constituency != 'all':
            conditions.append("b.constituency = ?")
            params.append(constituency)
        if station and station != 'all':
            conditions.append("b.polling_station = ?")
            params.append(station)
        if booth_id and booth_id != 'all':
            conditions.append("b.id = ?")
            params.append(int(booth_id))

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY b.district ASC, b.constituency ASC, b.id ASC"

        cursor.execute(sql, tuple(params))
        booths = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': booths})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@admin_bp.route('/admin/add_booth', methods=['POST'])
def add_booth():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.json or {}
    booth_code = data.get('booth_code', '').strip()
    booth_name = data.get('booth_name', '').strip()
    district = data.get('district', 'Pune').strip()
    constituency = data.get('constituency', 'Shivaji Nagar').strip()
    polling_station = data.get('polling_station', 'Main Center').strip()
    region = data.get('region', '').strip() or f"{district} - {constituency}"
    
    if not booth_code or not booth_name:
        return jsonify({'status': 'error', 'message': 'Booth code and name are required'})

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("""
            INSERT INTO booths (booth_code, booth_name, district, constituency, polling_station, region, status, last_active)
            VALUES (?, ?, ?, ?, ?, ?, 'OFFLINE', ?)
        """, (booth_code, booth_name, district, constituency, polling_station, region, now_str))
        conn.commit()
        return jsonify({'status': 'success', 'message': f'Polling booth {booth_code} registered in {district} ({constituency}) successfully'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': f'Booth code {booth_code} already exists'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. REGISTERED VOTERS (FILTERED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/admin/get_voters')
def get_voters():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    district = request.args.get('district', '').strip()
    constituency = request.args.get('constituency', '').strip()
    station = request.args.get('station', '').strip()
    booth_id = request.args.get('booth_id', '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            SELECT v.v_id, v.name, v.gender, v.dob,
                   v.gram_panchayat, v.panchayat_samiti, v.zilha_parishad,
                   v.mahanagarpalika, v.nagar_parishad, v.nagar_panchayat,
                   v.reg_date,
                   b.booth_code, b.booth_name, b.district, b.constituency, b.polling_station
            FROM voters v
            LEFT JOIN booths b ON v.assigned_booth_id = b.id
        """
        conditions = []
        params = []
        if district and district != 'all':
            conditions.append("b.district = ?")
            params.append(district)
        if constituency and constituency != 'all':
            conditions.append("b.constituency = ?")
            params.append(constituency)
        if station and station != 'all':
            conditions.append("b.polling_station = ?")
            params.append(station)
        if booth_id and booth_id != 'all':
            conditions.append("v.assigned_booth_id = ?")
            params.append(int(booth_id))

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
            
        sql += " ORDER BY v.reg_date DESC"
        cursor.execute(sql, tuple(params))
        voters = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': voters})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. CENTRALIZED VOTED LOG (FILTERED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/admin/get_voted_log')
def get_voted_log():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    district = request.args.get('district', '').strip()
    constituency = request.args.get('constituency', '').strip()
    station = request.args.get('station', '').strip()
    booth_id = request.args.get('booth_id', '').strip()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            SELECT vl.id, vl.v_id, vl.voter_name, vl.election,
                   vl.booth_code, vl.booth_officer, vl.region, vl.voted_at,
                   b.booth_name, b.district, b.constituency, b.polling_station
            FROM voted_log vl
            LEFT JOIN booths b ON vl.booth_id = b.id
        """
        conditions = []
        params = []
        if district and district != 'all':
            conditions.append("b.district = ?")
            params.append(district)
        if constituency and constituency != 'all':
            conditions.append("b.constituency = ?")
            params.append(constituency)
        if station and station != 'all':
            conditions.append("b.polling_station = ?")
            params.append(station)
        if booth_id and booth_id != 'all':
            conditions.append("vl.booth_id = ?")
            params.append(int(booth_id))

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
            
        sql += " ORDER BY vl.voted_at DESC"
        cursor.execute(sql, tuple(params))
        logs = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': logs})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. OFFICER MANAGEMENT & CONSTITUENCY-WISE ERO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/admin/add_officer', methods=['POST'])
def add_officer():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    mobile = (data.get('mobile') or '').strip()
    role = (data.get('role') or '').strip()
    booth_id = data.get('booth_id')
    district = (data.get('district') or '').strip()
    constituency = (data.get('constituency') or '').strip()
    location = (data.get('location') or '').strip()

    if not username or not password or not mobile or not role:
        return jsonify({'status': 'error', 'message': 'Username, Password, Authorized Mobile Number, and Role are required'})

    # Validate 10-digit mobile number
    clean_mobile = ''.join(filter(str.isdigit, mobile))
    if len(clean_mobile) != 10:
        return jsonify({'status': 'error', 'message': 'Please enter a valid 10-digit mobile number for OTP authorization'})

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        parsed_booth_id = int(booth_id) if booth_id and str(booth_id).isdigit() else None

        # ── 1. ERO Specific Validations: 1 ERO Per Assembly Constituency ──
        if role == 'ERO':
            if not district or not constituency:
                return jsonify({
                    'status': 'error',
                    'message': 'District (जिल्हा) and Assembly Constituency (मतदारसंघ) are mandatory when appointing an ERO officer.'
                })

            # Check if an ERO is already appointed for this constituency
            cursor.execute("""
                SELECT id, username, district, constituency
                FROM officers
                WHERE role='ERO' AND (
                    LOWER(constituency) = LOWER(?) OR
                    (LOWER(district) = LOWER(?) AND LOWER(constituency) = LOWER(?))
                )
            """, (constituency, district, constituency))
            existing_ero = cursor.fetchone()

            if existing_ero:
                return jsonify({
                    'status': 'error',
                    'message': f'️ Constituency Allocation Conflict: Assembly Constituency "{constituency}" ({district}) already has an assigned ERO ("{existing_ero["username"]}"). According to Election Commission rules, each Constituency can only have ONE ERO officer. Please delete or reassign the current ERO first.'
                })

            if not location:
                location = f"{district} - {constituency}"

        elif role == 'ARO':
            if not district or not constituency:
                return jsonify({
                    'status': 'error',
                    'message': 'District (जिल्हा) and Assembly Constituency (मतदारसंघ) are mandatory when appointing an ARO officer.'
                })
            if not location:
                location = f"{district} - {constituency} ARO Office"

        elif not location:
            location = district or "Default Station"

        cursor.execute(
            """INSERT INTO officers (username, password, mobile, location, role, booth_id, created_at, district, constituency)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, password, clean_mobile, location, role, parsed_booth_id, now_str, district, constituency)
        )
        conn.commit()

        if role == 'ERO':
            succ_msg = f'ERO ({username}) successfully appointed as the sole Electoral Registration Officer for Constituency: "{constituency}" ({district}).'
        elif role == 'ARO':
            succ_msg = f'ARO ({username}) successfully appointed as Assistant Returning Officer for Constituency: "{constituency}" ({district}).'
        else:
            succ_msg = f'{role} ({username}) registered with Mobile +91 {clean_mobile} successfully'

        return jsonify({'status': 'success', 'message': succ_msg})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': f'Officer username "{username}" already exists. Please choose a unique username.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@admin_bp.route('/admin/get_officers', methods=['GET'])
def get_officers():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.username, o.mobile, o.location, o.role, o.booth_id, o.district, o.constituency, o.created_at,
                   b.booth_code, b.booth_name
            FROM officers o
            LEFT JOIN booths b ON o.booth_id = b.id
            ORDER BY o.role ASC, o.id DESC
        """)
        officers = [dict(row) for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'data': officers})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@admin_bp.route('/admin/delete_officer/<int:officer_id>', methods=['POST', 'DELETE'])
def delete_officer(officer_id):
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, role, constituency, district FROM officers WHERE id=?", (officer_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Officer not found'})
        
        cursor.execute("DELETE FROM officers WHERE id=?", (officer_id,))
        conn.commit()

        loc_str = f" for {row['constituency']}" if row['constituency'] else ""
        return jsonify({
            'status': 'success',
            'message': f'{row["role"]} "{row["username"]}"{loc_str} was successfully unassigned & deleted.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. SYSTEM RESET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/reset_system', methods=['POST'])
def reset_system():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Reset all voted (0) back to eligible (1) across all election tiers
        for col in ['gram_panchayat', 'panchayat_samiti', 'zilha_parishad', 'mahanagarpalika', 'nagar_parishad', 'nagar_panchayat', 'lok_sabha', 'vidhan_sabha']:
            cursor.execute(f"UPDATE voters SET {col} = 1 WHERE {col} = 0")

        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("UPDATE voters SET reg_date = ?", (today,))

        cursor.execute("DELETE FROM voted_log")
        cursor.execute("DELETE FROM booth_activity_log")

        conn.commit()

        return jsonify({
            'status': 'success',
            'message': 'सिस्टीम यशस्वीरीत्या रीसेट झाली! सर्व मतदान केंद्रांचे रेकॉर्ड्स रीसेट झाले आहेत.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. BLOCKCHAIN LEDGER & VERIFICATION ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/admin/blockchain_ledger')
def blockchain_ledger():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    conn = None
    try:
        from utils.blockchain import Blockchain
        conn = get_db_connection()
        
        # Ensure Genesis Block exists
        Blockchain.init_genesis_block(conn)
        
        blocks = Blockchain.get_ledger_records(conn, limit=50)
        integrity = Blockchain.verify_chain_integrity(conn)

        return jsonify({
            'status': 'success',
            'data': {
                'blocks': blocks,
                'integrity': integrity,
                'total_blocks': integrity['total_blocks'],
                'is_valid': integrity['is_valid'],
                'latest_hash': integrity['latest_hash']
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@admin_bp.route('/admin/verify_blockchain', methods=['POST'])
def verify_blockchain():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    conn = None
    try:
        from utils.blockchain import Blockchain
        conn = get_db_connection()
        integrity = Blockchain.verify_chain_integrity(conn)

        return jsonify({
            'status': 'success',
            'data': integrity,
            'message': 'Blockchain cryptographic audit completed successfully.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. BOOTH OFFICER NETWORK QUERIES CONTROL ROOM (MAIN ELECTION OFFICER)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@admin_bp.route('/api/admin/network_queries', methods=['GET'])
def admin_get_network_queries():
    """Returns all booth network queries for the Main Election Officer dashboard."""
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    status_filter = request.args.get('status', '').strip().upper()
    urgency_filter = request.args.get('urgency', '').strip().upper()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        sql = """
            SELECT id, query_id, booth_id, booth_code, booth_name, officer_username, officer_mobile,
                   location, issue_type, urgency, network_status, description, status,
                   admin_response, resolved_by, resolved_at, created_at
            FROM booth_network_queries
        """
        clauses = []
        params = []
        if status_filter and status_filter != 'ALL':
            clauses.append("status = ?")
            params.append(status_filter)
        if urgency_filter and urgency_filter != 'ALL':
            clauses.append("urgency = ?")
            params.append(urgency_filter)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY CASE WHEN status='PENDING' THEN 1 WHEN status='ACKNOWLEDGED' THEN 2 ELSE 3 END, id DESC LIMIT 200"

        cursor.execute(sql, tuple(params))
        rows = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT status, COUNT(*) as cnt FROM booth_network_queries GROUP BY status")
        stat_rows = cursor.fetchall()
        stats = { 'PENDING': 0, 'ACKNOWLEDGED': 0, 'RESOLVED': 0, 'TOTAL': len(rows) }
        for r in stat_rows:
            stats[r['status']] = r['cnt']

        return jsonify({'status': 'success', 'data': rows, 'stats': stats})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@admin_bp.route('/api/admin/network_queries/respond', methods=['POST'])
def admin_respond_network_query():
    """Allows Main Election Officer to Acknowledge or Resolve a Booth Officer Network Query."""
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    data = request.json or {}
    query_id = (data.get('query_id') or '').strip()
    new_status = (data.get('status') or 'ACKNOWLEDGED').strip().upper()
    admin_response = (data.get('admin_response') or '').strip()

    if not query_id:
        return jsonify({'status': 'error', 'message': 'Query ID is required.'}), 400

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    resolved_by = session.get('admin_username', 'Main Election Officer')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE booth_network_queries
            SET status = ?, admin_response = COALESCE(NULLIF(?, ''), admin_response),
                resolved_by = ?, resolved_at = ?
            WHERE query_id = ?
        """, (new_status, admin_response, resolved_by, now_str, query_id))

        cursor.execute("""
            INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
            VALUES (1, 'Main Election Officer', 'NETWORK_QUERY_UPDATED', ?, ?)
        """, (f"Query #{query_id} updated to {new_status} by {resolved_by}: {admin_response}", now_str))

        conn.commit()
        return jsonify({'status': 'success', 'message': f'Network Query #{query_id} updated to {new_status}.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass