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
            assigned_booth_id INTEGER
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
    add_col_if_missing("officers", "booth_id", "INTEGER")
    add_col_if_missing("officers", "mobile", "TEXT DEFAULT '9876543210'")
    add_col_if_missing("officers", "created_at", "TEXT")
    add_col_if_missing("voted_log", "booth_id", "INTEGER")
    add_col_if_missing("voted_log", "booth_code", "TEXT")

    # Ensure all existing officers have a valid mobile number
    cursor.execute("UPDATE officers SET mobile = '9876543210' WHERE mobile IS NULL OR mobile = ''")
    cursor.execute("UPDATE officers SET mobile = '9876543220' WHERE username = 'officer1'")
    cursor.execute("UPDATE officers SET mobile = '9876543221' WHERE username = 'officer'")
    cursor.execute("UPDATE officers SET mobile = '9876543210' WHERE username = 'booth1'")
    cursor.execute("UPDATE officers SET mobile = '9876543211' WHERE username = 'booth2'")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SEED 6 STANDARD ELECTION CYCLES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    election_list = [
        ('GP_2026', 'ग्रामपंचायत निवडणूक २०२६ (Gram Panchayat Election)', 'gram_panchayat', 'ACTIVE'),
        ('PS_2026', 'पंचायत समिती निवडणूक २०२६ (Panchayat Samiti Election)', 'panchayat_samiti', 'ACTIVE'),
        ('ZP_2026', 'जिल्हा परिषद निवडणूक २०२६ (Zilha Parishad Election)', 'zilha_parishad', 'ACTIVE'),
        ('MNC_2026', 'महानगरपालिका निवडणूक २०२६ (Mahanagarpalika Election)', 'mahanagarpalika', 'ACTIVE'),
        ('NP_2026', 'नगरपालिका / नगरपरिषद निवडणूक २०२६ (Nagarpalika / Nagar Parishad Election)', 'nagar_parishad', 'ACTIVE'),
        ('NPT_2026', 'नगरपंचायत निवडणूक २०२६ (Nagar Panchayat Election)', 'nagar_panchayat', 'ACTIVE')
    ]

    for code, name, e_type, st in election_list:
        cursor.execute("SELECT id FROM elections WHERE election_code=?", (code,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO elections (election_code, election_name, election_type, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (code, name, e_type, st, now_str))

    # Seed Default Polling Booths with Hierarchy
    cursor.execute("SELECT COUNT(*) FROM booths")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO booths (booth_code, booth_name, district, constituency, polling_station, region, status, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ('BOOTH-001', 'Booth 001 - Room 101', 'Pune', 'Shivaji Nagar', 'Modern High School & Junior College', 'Pune Central Ward 1', 'ONLINE', now_str),
            ('BOOTH-002', 'Booth 002 - Room 102', 'Pune', 'Shivaji Nagar', 'Modern High School & Junior College', 'Pune Central Ward 1', 'ONLINE', now_str),
            ('BOOTH-003', 'Booth 003 - Room 201', 'Pune', 'Kothrud', 'MIT World Peace Primary School', 'Pune West Ward 4', 'OFFLINE', now_str),
            ('BOOTH-004', 'Booth 004 - Room 1', 'Mumbai', 'Colaba', 'St. Xavier High School Campus', 'Mumbai South Ward 12', 'OFFLINE', now_str),
            ('BOOTH-005', 'Booth 005 - Room 3', 'Ahmednagar', 'Sangamner', 'D.G.V. Vidyalaya High School', 'Sangamner Central', 'ONLINE', now_str),
            ('BOOTH-006', 'Booth 006 - Room 2', 'Chhatrapati Sambhajinagar', 'Aurangabad Central', 'Govt Model Arts & Science College', 'City Centre Ward 2', 'OFFLINE', now_str)
        ])
        print("[Database] Seeded default polling booths with district & constituency hierarchy.")

    # Map any existing unassigned booth officers to Booth 1
    cursor.execute("UPDATE officers SET booth_id = 1 WHERE role='Booth Officer' AND (booth_id IS NULL OR booth_id = 0)")

    # Ensure default booth test accounts exist with mobile numbers
    cursor.execute("SELECT id FROM officers WHERE username='booth1'")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO officers (username, password, mobile, location, role, booth_id, created_at)
            VALUES ('booth1', 'booth123', '9876543210', 'Pune Ward 1', 'Booth Officer', 1, ?)
        """, (now_str,))

    cursor.execute("SELECT id FROM officers WHERE username='booth2'")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO officers (username, password, mobile, location, role, booth_id, created_at)
            VALUES ('booth2', 'booth123', '9876543211', 'Pune Ward 4', 'Booth Officer', 2, ?)
        """, (now_str,))

    # Ensure default Registration Officer test accounts exist with mobile numbers
    cursor.execute("SELECT id FROM officers WHERE username='officer1'")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO officers (username, password, mobile, location, role, booth_id, created_at)
            VALUES ('officer1', 'officer123', '9876543220', 'Pune Head Office', 'Registration Officer', NULL, ?)
        """, (now_str,))

    cursor.execute("SELECT id FROM officers WHERE username='officer'")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO officers (username, password, mobile, location, role, booth_id, created_at)
            VALUES ('officer', 'officer123', '9876543221', 'Pune Head Office', 'Registration Officer', NULL, ?)
        """, (now_str,))

    # Initialize Genesis Block if empty
    try:
        from utils.blockchain import Blockchain
        Blockchain.init_genesis_block(conn)
    except Exception as e:
        print(f"[Database] Blockchain init warning: {e}")

    conn.commit()
    conn.close()
    print("[Database] Multi-Booth database initialized successfully.")
