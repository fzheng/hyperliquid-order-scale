"""User state storage with JSON file persistence."""

import json
import logging
import os
import tempfile
import threading
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

# Storage file path - uses DATA_DIR env var for Railway, falls back to local
DATA_DIR = os.environ.get("DATA_DIR", ".")
STORAGE_FILE = Path(DATA_DIR) / "user_state.json"

# Log storage paths on module load
logger.info(f"Storage DATA_DIR: {DATA_DIR}")
logger.info(f"Users file: {Path(DATA_DIR) / 'registered_users.json'}")

# Thread lock for safe concurrent access
_storage_lock = threading.Lock()


def _atomic_write(file_path: Path, data: str):
    """Write data atomically using temp file + replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        # os.replace is atomic on both Windows and Unix
        os.replace(tmp_path, file_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _load_all_unlocked() -> dict:
    """Load all user states from file (caller must hold lock)."""
    if not STORAGE_FILE.exists():
        return {}
    try:
        with open(STORAGE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_all_unlocked(data: dict):
    """Save all user states to file (caller must hold lock)."""
    _atomic_write(STORAGE_FILE, json.dumps(data, indent=2))


def get_user_position(user_id: int | str) -> dict | None:
    """Get a user's stored position.

    Returns dict with keys: size (signed Decimal), entry_price (Decimal)
    Returns None if user has no stored position.
    """
    with _storage_lock:
        data = _load_all_unlocked()
        user_key = str(user_id)

        if user_key not in data:
            return None

        user_data = data[user_key]
        return {
            "size": Decimal(str(user_data["size"])),
            "entry_price": Decimal(str(user_data["entry_price"])),
        }


def set_user_position(user_id: int | str, size: Decimal, entry_price: Decimal):
    """Set a user's position.

    Args:
        user_id: Telegram user ID
        size: Position size (positive for long, negative for short)
        entry_price: Entry price in USD
    """
    with _storage_lock:
        data = _load_all_unlocked()
        user_key = str(user_id)

        data[user_key] = {
            "size": str(size),
            "entry_price": str(entry_price),
        }

        _save_all_unlocked(data)


def clear_user_position(user_id: int | str):
    """Clear a user's stored position."""
    with _storage_lock:
        data = _load_all_unlocked()
        user_key = str(user_id)

        if user_key in data:
            del data[user_key]
            _save_all_unlocked(data)


# --- User tracking for notifications ---

USERS_FILE = Path(DATA_DIR) / "registered_users.json"
_users_lock = threading.Lock()


def _load_users_unlocked() -> set:
    """Load registered user IDs (caller must hold lock)."""
    if not USERS_FILE.exists():
        return set()
    try:
        with open(USERS_FILE, "r") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, IOError):
        return set()


def _save_users_unlocked(users: set):
    """Save registered user IDs (caller must hold lock)."""
    _atomic_write(USERS_FILE, json.dumps(list(users)))


def register_user(user_id: int | str):
    """Register a user for notifications."""
    with _users_lock:
        users = _load_users_unlocked()
        user_int = int(user_id)
        is_new = user_int not in users
        users.add(user_int)
        _save_users_unlocked(users)
        if is_new:
            logger.info(f"Registered new user {user_int}, total users: {len(users)}")


def get_all_users() -> list[int]:
    """Get all registered user IDs."""
    with _users_lock:
        users = list(_load_users_unlocked())
        logger.debug(f"Loaded {len(users)} registered users from {USERS_FILE}")
        return users


# --- Previous state for change detection ---

PREV_STATE_FILE = Path(DATA_DIR) / "prev_state.json"
_prev_state_lock = threading.Lock()


def get_previous_state() -> dict | None:
    """Get the previous weishen state for comparison."""
    with _prev_state_lock:
        if not PREV_STATE_FILE.exists():
            return None
        try:
            with open(PREV_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None


def save_previous_state(state: dict):
    """Save current state for future comparison."""
    # Convert Decimals to strings for JSON serialization
    serializable = {
        "direction": state.get("direction"),
        "size": str(state.get("size", 0)),
        "entry_price": str(state.get("entry_price", 0)),
        "orders": [
            {
                "oid": o.get("oid"),
                "side": o.get("side"),
                "sz": o.get("sz"),
                "limitPx": o.get("limitPx"),
            }
            for o in state.get("orders", [])
        ],
    }
    with _prev_state_lock:
        _atomic_write(PREV_STATE_FILE, json.dumps(serializable, indent=2))
