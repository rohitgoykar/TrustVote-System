import os
import sys
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in [BASE_DIR, os.getcwd()]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from config import DB_PATH, DATABASE_URL, DB_TYPE
except ImportError:
    DB_PATH = os.path.join(BASE_DIR, "voters.db")
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    DB_TYPE = "postgres" if DATABASE_URL else "sqlite"


def get_db_connection():
    """
    Returns a database connection.
    Supports PostgreSQL if DATABASE_URL is configured (cloud),
    otherwise falls back to local SQLite with WAL mode and concurrency locks.
    """
    if DB_TYPE == "postgres":
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except ImportError:
            print("[Database] psycopg2 not installed, falling back to SQLite.")
    
    conn = sqlite3.connect(DB_PATH, timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 60000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception as e:
        print(f"[Database] WAL pragma note: {e}")
    return conn

def init_db():
    """
    Initializes and auto-migrates all tables for the Multi-Booth Architecture:
    Election -> District -> Constituency -> Polling Station -> Booth -> Officer -> Voter -> Vote Log
    """
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 60000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    cursor = conn.cursor()

    # 1. Elections Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS elections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_code TEXT UNIQUE NOT NULL,
            election_name TEXT NOT NULL,
            election_type TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL
        )
    """)

    # 2. Polling Booths Table (with Hierarchy: District -> Constituency -> Polling Station -> Booth)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS booths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booth_code TEXT UNIQUE NOT NULL,
            booth_name TEXT NOT NULL,
            district TEXT DEFAULT 'Pune',
            constituency TEXT DEFAULT 'Shivaji Nagar',
            polling_station TEXT DEFAULT 'Main Polling Center',
            region TEXT NOT NULL,
            status TEXT DEFAULT 'OFFLINE',
            last_active TEXT
        )
    """)

    # 3. Officers Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS officers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            mobile TEXT DEFAULT '9876543210',
            location TEXT NOT NULL,
            role TEXT NOT NULL,
            booth_id INTEGER,
            created_at TEXT
        )
    """)

    # 4. Voters Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voters (
            v_id TEXT PRIMARY KEY,
            name TEXT,
            gender TEXT,
            photo TEXT,
            district TEXT DEFAULT 'Pune',
            constituency TEXT DEFAULT 'Shivaji Nagar',
            gram_panchayat INTEGER DEFAULT 1,
            panchayat_samiti INTEGER DEFAULT 1,
            zilha_parishad INTEGER DEFAULT 1,
            mahanagarpalika INTEGER DEFAULT 1,
            nagar_parishad INTEGER DEFAULT 1,
            nagar_panchayat INTEGER DEFAULT 1,
            gram_panchayat_name TEXT,
            panchayat_samiti_name TEXT,
            zilha_parishad_name TEXT,
            mahanagarpalika_name TEXT,
            nagar_parishad_name TEXT,
            nagar_panchayat_name TEXT,
            reg_date TEXT,
            dob TEXT,
            assigned_booth_id INTEGER,
            application_id TEXT
        )
    """)

    # 5. Voted Log Table (Centralized Multi-Booth Vote Audit Trail)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voted_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            v_id TEXT NOT NULL,
            voter_name TEXT NOT NULL,
            election TEXT NOT NULL,
            booth_officer TEXT NOT NULL,
            region TEXT NOT NULL,
            voted_at TEXT NOT NULL,
            booth_id INTEGER,
            booth_code TEXT
        )
    """)

    # 6. Booth Activity & Heartbeat Log Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS booth_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booth_id INTEGER,
            officer_username TEXT,
            action TEXT,
            details TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    # 7. Immutable Cryptographic Blockchain Ledger Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blockchain_ledger (
            block_index INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            voter_id TEXT NOT NULL,
            voter_id_hash TEXT NOT NULL,
            voter_name TEXT NOT NULL,
            election TEXT NOT NULL,
            booth_code TEXT NOT NULL,
            booth_id INTEGER,
            booth_officer TEXT NOT NULL,
            region TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            block_hash TEXT NOT NULL,
            nonce INTEGER DEFAULT 0,
            is_verified INTEGER DEFAULT 1
        )
    """)

    # 8. Booth Network Queries & Emergency Alerts Table (Dispatched to Main Election Officer)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS booth_network_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id TEXT UNIQUE NOT NULL,
            booth_id INTEGER,
            booth_code TEXT NOT NULL,
            booth_name TEXT NOT NULL,
            officer_username TEXT NOT NULL,
            officer_mobile TEXT,
            location TEXT,
            issue_type TEXT NOT NULL,
            urgency TEXT DEFAULT 'HIGH',
            network_status TEXT DEFAULT 'OFFLINE',
            description TEXT,
            status TEXT DEFAULT 'PENDING',
            admin_response TEXT,
            resolved_by TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # DYNAMIC MIGRATIONS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def add_col_if_missing(table, col, col_def):
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cursor.fetchall()]
            if col not in cols:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                conn.commit()
                print(f"[Database] Migrated {table}: added column {col}")
        except Exception as e:
            print(f"[Database] Migration note ({table}.{col}): {e}")

    add_col_if_missing("booths", "district", "TEXT DEFAULT 'Pune'")
    add_col_if_missing("booths", "constituency", "TEXT DEFAULT 'Shivaji Nagar'")
    add_col_if_missing("booths", "polling_station", "TEXT DEFAULT 'Main Polling Center'")
    add_col_if_missing("booths", "offline_authorized", "INTEGER DEFAULT 0")
    add_col_if_missing("booths", "offline_token", "TEXT")
    add_col_if_missing("booths", "offline_authorized_by", "TEXT")
    add_col_if_missing("booths", "offline_authorized_at", "TEXT")
    add_col_if_missing("booths", "offline_valid_until", "TEXT")
    add_col_if_missing("voters", "district", "TEXT DEFAULT 'Pune'")
    add_col_if_missing("voters", "constituency", "TEXT DEFAULT 'Shivaji Nagar'")
    add_col_if_missing("voters", "gram_panchayat", "INTEGER DEFAULT 1")
    add_col_if_missing("voters", "panchayat_samiti", "INTEGER DEFAULT 1")
    add_col_if_missing("voters", "zilha_parishad", "INTEGER DEFAULT 1")
    add_col_if_missing("voters", "mahanagarpalika", "INTEGER DEFAULT 1")
    add_col_if_missing("voters", "nagar_parishad", "INTEGER DEFAULT 1")
    add_col_if_missing("voters", "nagar_panchayat", "INTEGER DEFAULT 1")
    add_col_if_missing("voters", "gram_panchayat_name", "TEXT")
    add_col_if_missing("voters", "panchayat_samiti_name", "TEXT")
    add_col_if_missing("voters", "zilha_parishad_name", "TEXT")
    add_col_if_missing("voters", "mahanagarpalika_name", "TEXT")
    add_col_if_missing("voters", "nagar_parishad_name", "TEXT")
    add_col_if_missing("voters", "nagar_panchayat_name", "TEXT")
    add_col_if_missing("voters", "dob", "TEXT")
    add_col_if_missing("voters", "assigned_booth_id", "INTEGER")
    add_col_if_missing("voters", "ero_status", "TEXT DEFAULT 'APPROVED'")
    add_col_if_missing("voters", "ero_remarks", "TEXT DEFAULT 'Direct Registration - Certified'")
    add_col_if_missing("voters", "ero_decided_by", "TEXT")
    add_col_if_missing("voters", "ero_decided_at", "TEXT")
    add_col_if_missing("voters", "form6_file", "TEXT")
    add_col_if_missing("voters", "relative_type", "TEXT DEFAULT 'Father'")
    add_col_if_missing("voters", "relative_name", "TEXT")
    add_col_if_missing("voters", "mobile", "TEXT")
    add_col_if_missing("voters", "email", "TEXT")
    add_col_if_missing("voted_log", "transaction_id", "TEXT")
    add_col_if_missing("voted_log", "offline_token", "TEXT")
    add_col_if_missing("blockchain_ledger", "transaction_id", "TEXT")
    add_col_if_missing("blockchain_ledger", "offline_token", "TEXT")
    add_col_if_missing("voters", "aadhaar_no", "TEXT")
    add_col_if_missing("voters", "address_line", "TEXT")
    add_col_if_missing("voters", "pincode", "TEXT")
    add_col_if_missing("voters", "taluka", "TEXT")
    add_col_if_missing("voters", "dob_proof_type", "TEXT")
    add_col_if_missing("voters", "application_id", "TEXT")
    add_col_if_missing("officers", "booth_id", "INTEGER")
    add_col_if_missing("officers", "mobile", "TEXT DEFAULT '9876543210'")
    add_col_if_missing("officers", "created_at", "TEXT")
    add_col_if_missing("officers", "district", "TEXT")
    add_col_if_missing("officers", "constituency", "TEXT")
    add_col_if_missing("voted_log", "booth_id", "INTEGER")
    add_col_if_missing("voted_log", "booth_code", "TEXT")

    # (Optional officer mobile updates only if table has records)
    cursor.execute("UPDATE officers SET mobile = '9876543210' WHERE mobile IS NULL OR mobile = ''")

    # Seed Default ARO (Assistant Returning Officer) test account if missing
    cursor.execute("SELECT id FROM officers WHERE username='aro1'")
    if not cursor.fetchone():
        now_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("""
            INSERT INTO officers (username, password, mobile, location, role, district, constituency, booth_id, created_at)
            VALUES ('aro1', 'aro123', '9876543230', 'Pune Central ARO Office', 'ARO', 'Pune', 'Shivaji Nagar', NULL, ?)
        """, (now_dt,))
        print("[Database] Seeded default ARO test officer account (aro1 / aro123).")

    # Initialize Genesis Block if empty
    try:
        from utils.blockchain import Blockchain
        Blockchain.init_genesis_block(conn)
    except Exception as e:
        print(f"[Database] Blockchain init warning: {e}")

    conn.commit()
    conn.close()
    print("[Database] Multi-Booth database initialized successfully.")

    # Auto-initialize and sync all constituency-specific isolated databases
    try:
        init_all_constituency_databases()
    except Exception as e:
        print(f"[Database] Constituency databases init note: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONSTITUENCY-SPECIFIC ISOLATED DATABASE MANAGEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTITUENCY_DBS_DIR = os.path.join(BASE_DIR, "constituency_databases")
os.makedirs(CONSTITUENCY_DBS_DIR, exist_ok=True)

def get_constituency_slug(name):
    """Converts constituency name to clean filesystem slug."""
    if not name:
        return "general"
    clean = "".join(c if c.isalnum() else "_" for c in str(name).strip().lower())
    clean = "_".join(filter(None, clean.split("_")))
    return clean or "general"

def get_constituency_db_path(constituency_name):
    """Returns absolute path to the constituency's dedicated SQLite database file."""
    slug = get_constituency_slug(constituency_name)
    return os.path.join(CONSTITUENCY_DBS_DIR, f"constituency_{slug}.db")

def get_constituency_db_connection(constituency_name):
    """
    Returns an active SQLite connection to the isolated constituency database.
    """
    db_file = get_constituency_db_path(constituency_name)
    conn = sqlite3.connect(db_file, timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 60000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    return conn

def init_constituency_db(constituency_name):
    """
    Initializes schema for a constituency-isolated database.
    """
    conn = get_constituency_db_connection(constituency_name)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voters (
            v_id TEXT PRIMARY KEY,
            name TEXT,
            gender TEXT,
            photo TEXT,
            district TEXT,
            constituency TEXT,
            gram_panchayat INTEGER DEFAULT 1,
            panchayat_samiti INTEGER DEFAULT 1,
            zilha_parishad INTEGER DEFAULT 1,
            mahanagarpalika INTEGER DEFAULT 1,
            nagar_parishad INTEGER DEFAULT 1,
            nagar_panchayat INTEGER DEFAULT 1,
            gram_panchayat_name TEXT,
            panchayat_samiti_name TEXT,
            zilha_parishad_name TEXT,
            mahanagarpalika_name TEXT,
            nagar_parishad_name TEXT,
            nagar_panchayat_name TEXT,
            reg_date TEXT,
            dob TEXT,
            assigned_booth_id INTEGER,
            ero_status TEXT DEFAULT 'APPROVED',
            application_id TEXT,
            aadhaar_no TEXT,
            mobile TEXT,
            face_encoding_cached TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS booths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booth_code TEXT UNIQUE NOT NULL,
            booth_name TEXT NOT NULL,
            district TEXT,
            constituency TEXT,
            polling_station TEXT,
            region TEXT,
            status TEXT DEFAULT 'ONLINE',
            offline_authorized INTEGER DEFAULT 0,
            offline_token TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voted_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            v_id TEXT NOT NULL,
            voter_name TEXT NOT NULL,
            election TEXT NOT NULL,
            booth_officer TEXT NOT NULL,
            region TEXT NOT NULL,
            voted_at TEXT NOT NULL,
            booth_id INTEGER,
            booth_code TEXT,
            transaction_id TEXT,
            offline_token TEXT,
            sync_status TEXT DEFAULT 'SYNCED'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS offline_sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT UNIQUE NOT NULL,
            v_id TEXT NOT NULL,
            voter_name TEXT,
            election TEXT NOT NULL,
            booth_code TEXT,
            booth_officer TEXT,
            voted_at TEXT NOT NULL,
            offline_token TEXT,
            sync_status TEXT DEFAULT 'PENDING',
            synced_at TEXT,
            sync_response TEXT
        )
    """)

    conn.commit()
    conn.close()

def sync_master_to_constituency_db(constituency_name):
    """
    Exports/Synchronizes voters and booths from master DB (voters.db)
    to the specific isolated constituency database.
    """
    if not constituency_name:
        return 0

    init_constituency_db(constituency_name)

    master_conn = get_db_connection()
    m_cursor = master_conn.cursor()

    m_cursor.execute("""
        SELECT v_id, name, gender, photo, district, constituency,
               gram_panchayat, panchayat_samiti, zilha_parishad,
               mahanagarpalika, nagar_parishad, nagar_panchayat,
               gram_panchayat_name, panchayat_samiti_name, zilha_parishad_name,
               mahanagarpalika_name, nagar_parishad_name, nagar_panchayat_name,
               reg_date, dob, assigned_booth_id, ero_status, application_id,
               aadhaar_no, mobile
        FROM voters
        WHERE constituency = ? OR constituency LIKE ?
    """, (constituency_name, f"%{constituency_name}%"))
    voters = [dict(r) for r in m_cursor.fetchall()]

    m_cursor.execute("""
        SELECT id, booth_code, booth_name, district, constituency,
               polling_station, region, status, offline_authorized, offline_token
        FROM booths
        WHERE constituency = ? OR constituency LIKE ?
    """, (constituency_name, f"%{constituency_name}%"))
    booths = [dict(r) for r in m_cursor.fetchall()]

    master_conn.close()

    # Insert / Update into Constituency DB
    c_conn = get_constituency_db_connection(constituency_name)
    c_cursor = c_conn.cursor()

    for v in voters:
        c_cursor.execute("""
            INSERT OR REPLACE INTO voters (
                v_id, name, gender, photo, district, constituency,
                gram_panchayat, panchayat_samiti, zilha_parishad,
                mahanagarpalika, nagar_parishad, nagar_panchayat,
                gram_panchayat_name, panchayat_samiti_name, zilha_parishad_name,
                mahanagarpalika_name, nagar_parishad_name, nagar_panchayat_name,
                reg_date, dob, assigned_booth_id, ero_status, application_id,
                aadhaar_no, mobile
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            v['v_id'], v['name'], v['gender'], v['photo'], v['district'], v['constituency'],
            v['gram_panchayat'], v['panchayat_samiti'], v['zilha_parishad'],
            v['mahanagarpalika'], v['nagar_parishad'], v['nagar_panchayat'],
            v['gram_panchayat_name'], v['panchayat_samiti_name'], v['zilha_parishad_name'],
            v['mahanagarpalika_name'], v['nagar_parishad_name'], v['nagar_panchayat_name'],
            v['reg_date'], v['dob'], v['assigned_booth_id'], v['ero_status'], v['application_id'],
            v.get('aadhaar_no'), v.get('mobile')
        ))

    for b in booths:
        c_cursor.execute("""
            INSERT OR REPLACE INTO booths (
                id, booth_code, booth_name, district, constituency,
                polling_station, region, status, offline_authorized, offline_token
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            b['id'], b['booth_code'], b['booth_name'], b['district'], b['constituency'],
            b['polling_station'], b['region'], b['status'], b['offline_authorized'], b['offline_token']
        ))

    c_conn.commit()
    c_conn.close()
    return len(voters)

def init_all_constituency_databases():
    """
    Finds all distinct constituencies configured across the system and ensures
    their dedicated SQLite database is initialized and synchronized.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT constituency FROM voters WHERE constituency IS NOT NULL AND constituency != ''
        UNION
        SELECT DISTINCT constituency FROM booths WHERE constituency IS NOT NULL AND constituency != ''
        UNION
        SELECT DISTINCT constituency FROM officers WHERE constituency IS NOT NULL AND constituency != ''
    """)
    constituencies = [r[0] for r in cursor.fetchall() if r[0]]
    conn.close()

    if not constituencies:
        constituencies = ["Shivaji Nagar", "Kothrud", "Pune Cantonment", "Kasba Peth"]

    count_map = {}
    for c_name in constituencies:
        v_count = sync_master_to_constituency_db(c_name)
        count_map[c_name] = v_count

    print(f"[Database] Synchronized {len(constituencies)} Constituency Databases successfully.")
    return count_map

def list_all_constituency_databases():
    """
    Returns list of all available constituency database files with metadata.
    """
    constituency_map = {}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT district, constituency FROM voters WHERE constituency IS NOT NULL AND constituency != ''")
        for r in cursor.fetchall():
            constituency_map[r['constituency']] = r['district'] or 'Maharashtra'
        conn.close()
    except Exception:
        pass

    if not constituency_map:
        constituency_map = {"Shivaji Nagar": "Pune", "Kothrud": "Pune", "Pune Cantonment": "Pune"}

    results = []
    for c_name, district in constituency_map.items():
        slug = get_constituency_slug(c_name)
        db_path = get_constituency_db_path(c_name)
        file_size_kb = round(os.path.getsize(db_path) / 1024, 1) if os.path.exists(db_path) else 0.0
        
        v_count = 0
        b_count = 0
        if os.path.exists(db_path):
            try:
                c_conn = get_constituency_db_connection(c_name)
                c_cur = c_conn.cursor()
                c_cur.execute("SELECT COUNT(*) FROM voters")
                v_count = c_cur.fetchone()[0]
                c_cur.execute("SELECT COUNT(*) FROM booths")
                b_count = c_cur.fetchone()[0]
                c_conn.close()
            except Exception:
                pass

        results.append({
            "constituency": c_name,
            "district": district,
            "slug": slug,
            "db_filename": f"constituency_{slug}.db",
            "db_path": db_path,
            "exists": os.path.exists(db_path),
            "file_size_kb": file_size_kb,
            "voters_count": v_count,
            "booths_count": b_count,
            "status": "ACTIVE_ISOLATED_DB"
        })

    return results

