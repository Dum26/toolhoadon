"""Cloud paths, separate from the Windows application's files."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SESSION_DIR = DATA_DIR / "session"
DEBUG_DIR = BASE_DIR / "debug"
DB_PATH = DATA_DIR / "inventory.db"
STATE_PATH = SESSION_DIR / "storage_state.json"
LOCK_PATH = DATA_DIR / "sync.lock"
VA_URL = os.environ.get("VAONLINE_URL", "")
TIMEOUT_MS = 30000

for directory in (DATA_DIR, SESSION_DIR, DEBUG_DIR):
    directory.mkdir(parents=True, exist_ok=True)
