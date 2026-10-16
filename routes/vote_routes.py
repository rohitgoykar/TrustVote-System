from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session
from database import get_db_connection

vote_bp = Blueprint('vote', __name__)

@vote_bp.route('/verify', methods=['POST'])
def verify():
    if not (session.get('booth_logged_in') or session.get('admin_logged_in') or session.get('officer_logged_in') or session.get('aro_logged_in') or session.get('ero_logged_in')):
        return jsonify({"status": "Error", "message": "सत्र संपले आहे (Unauthorized: Session expired)"}), 401
    try:
        req      = request.json or {}
        vid      = req.get('qr', '').replace("ID:", "").strip()
        election = req.get('election', '').strip()
        face_ok  = req.get('face_verified', False)

        booth_id = session.get('booth_id', 1)
        booth_code = session.get('booth_code', 'BOOTH-001')
        booth_officer = session.get('booth_username') or session.get('admin_username') or session.get('aro_username') or session.get('ero_username') or 'Booth Officer'
        region = session.get('booth_location') or session.get('aro_location') or 'Polling Station'
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not face_ok:
            return jsonify({"status": "Error", "message": "Face verification required before voting!"})

        allowed = [
            "gram_panchayat",
            "panchayat_samiti",
            "zilha_parishad",
            "mahanagarpalika",
            "nagar_parishad",
            "nagar_panchayat"
        ]
        if election not in allowed:
            return jsonify({"status": "Error", "message": "Invalid election type"})

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT " + election + ", reg_date, name, assigned_booth_id, district, constituency FROM voters WHERE v_id=?", (vid,))
            result = cursor.fetchone()

            if not result:
                cursor.execute("""
                    INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                    VALUES (?, ?, 'REJECTED_UNKNOWN', ?, ?)
                """, (booth_id, booth_officer, f"Unknown Voter ID {vid} scanned", now_str))
                conn.commit()
                return jsonify({"status": "Error", "message": "Voter record not found in system!"})

            eligible     = result[0]
            reg_date_str = result[1]
            voter_name   = result[2]

            # NULL means not registered for this election
            if eligible is None:
                cursor.execute("""
                    INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                    VALUES (?, ?, 'NOT_REGISTERED_FOR_ELECTION', ?, ?)
                """, (booth_id, booth_officer, f"{voter_name} ({vid}) is not registered for {election}", now_str))
                conn.commit()
                return jsonify({
                    "status":  "Error",
                    "message": f"️ {voter_name} is not registered to vote in {election.replace('_', ' ').title()}."
                })

            reg_date    = datetime.strptime(reg_date_str, '%Y-%m-%d')
            expiry_date = reg_date + timedelta(days=5 * 365)

            if datetime.now() >= expiry_date:
                cursor.execute("""
                    INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                    VALUES (?, ?, 'EXPIRED_REGISTRATION', ?, ?)
                """, (booth_id, booth_officer, f"Expired voter registration {voter_name} ({vid})", now_str))
                conn.commit()
                return jsonify({
                    "status":  "Error",
                    "message": f"{voter_name}, your voter registration has expired. Please re-register."
                })

            # ── 1. If eligible (1), record the vote ──────────────────────────────
            if eligible == 1:
                # Mark as voted (0) for this election
                cursor.execute("UPDATE voters SET " + election + "=0 WHERE v_id=?", (vid,))

                # Log into Centralized voted_log table
                cursor.execute("""
                    INSERT INTO voted_log (v_id, voter_name, election, booth_officer, region, voted_at, booth_id, booth_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (vid, voter_name, election.replace('_', ' ').title(), booth_officer, region, now_str, booth_id, booth_code))

                # Mine & append immutable cryptographic block to Blockchain Ledger
                from utils.blockchain import Blockchain
                block = Blockchain.add_vote_block(
                    conn,
                    vid=vid,
                    voter_name=voter_name,
                    election=election.replace('_', ' ').title(),
                    booth_officer=booth_officer,
                    region=region,
                    booth_id=booth_id,
                    booth_code=booth_code,
                    timestamp=now_str
                )

                # Log booth audit activity
                cursor.execute("""
                    INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                    VALUES (?, ?, 'VOTE_RECORDED', ?, ?)
                """, (booth_id, booth_officer, f"Vote cast by {voter_name} ({election.replace('_', ' ').title()}) at {region} [{booth_code}] - Block #{block.index}", now_str))

                # Update booth last active timestamp
                cursor.execute("UPDATE booths SET last_active=?, status='ONLINE' WHERE id=?", (now_str, booth_id))

                conn.commit()
                return jsonify({
                    "status":  "Success",
                    "message": f"{voter_name}, your vote for {election.replace('_', ' ').title()} has been cryptographically secured on the Blockchain Ledger at {region} ({booth_code})!",
                    "blockchain_receipt": {
                        "block_index": block.index,
                        "block_hash": block.hash,
                        "previous_hash": block.previous_hash,
                        "timestamp": block.timestamp,
                        "voter_hash": block.voter_id_hash
                    }
                })

            # ── 2. If already voted (0), fetch previous voting station & block ───
            else:
                cursor.execute("""
                    SELECT vl.booth_code, vl.region, vl.booth_officer, vl.voted_at,
                           b.booth_name, b.district, b.constituency
                    FROM voted_log vl
                    LEFT JOIN booths b ON vl.booth_id = b.id
                    WHERE vl.v_id = ? AND LOWER(vl.election) = LOWER(?)
                    ORDER BY vl.id DESC
                    LIMIT 1
                """, (vid, election.replace('_', ' ').title()))
                prev_vote = cursor.fetchone()

                if prev_vote:
                    prev_loc = prev_vote['region'] or prev_vote['booth_name'] or prev_vote['booth_code']
                    prev_code = prev_vote['booth_code'] or 'BOOTH'
                    prev_time = prev_vote['voted_at']
                    alert_msg = f"मतदान नाकारले (Duplicate Vote Blocked): {voter_name}, तुम्ही {election.replace('_', ' ').title()} साठी आधीच '{prev_loc}' ({prev_code}) येथे {prev_time} वाजता मतदान केले आहे! दुसऱ्या प्रभागात/केंद्रात ({region} - {booth_code}) पुन्हा मतदान करता येणार नाही."
                else:
                    alert_msg = f"मतदान नाकारले: {voter_name}, तुम्ही {election.replace('_', ' ').title()} साठी आधीच मतदान केले आहे! एकाच निवडणुकीत दुसऱ्या केंद्रात पुन्हा मतदान करता येणार नाही."

                cursor.execute("""
                    INSERT INTO booth_activity_log (booth_id, officer_username, action, details, timestamp)
                    VALUES (?, ?, 'ALREADY_VOTED_BLOCKED', ?, ?)
                """, (booth_id, booth_officer, f"Blocked duplicate vote attempt by {voter_name} ({vid}) for {election.replace('_', ' ').title()} at {region} [{booth_code}]", now_str))

                conn.commit()

                return jsonify({
                    "status":  "Error",
                    "message": alert_msg
                })
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

    except Exception as e:
        return jsonify({"status": "Error", "message": f"Server error: {e}"})
