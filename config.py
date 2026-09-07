import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
DB_PATH = os.path.join(BASE_DIR, "voters.db")
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
ID_CARDS_DIR = os.path.join(BASE_DIR, "id_cards")

# Cloud Database Configuration
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DB_TYPE = "postgres" if DATABASE_URL else "sqlite"
SECRET_KEY = os.environ.get("SECRET_KEY", "super_secret_trustvote_key")
