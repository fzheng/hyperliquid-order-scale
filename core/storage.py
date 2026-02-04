"""User state storage with JSON file persistence."""

import json
import os
from decimal import Decimal
from pathlib import Path

# Storage file path - uses DATA_DIR env var for Railway, falls back to local
DATA_DIR = os.environ.get("DATA_DIR", ".")
STORAGE_FILE = Path(DATA_DIR) / "user_state.json"


def _load_all() -> dict:
    """Load all user states from file."""
    if not STORAGE_FILE.exists():
        return {}
    try:
        with open(STORAGE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_all(data: dict):
    """Save all user states to file."""
    STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STORAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user_position(user_id: int | str) -> dict | None:
    """Get a user's stored position.

    Returns dict with keys: size (signed Decimal), entry_price (Decimal)
    Returns None if user has no stored position.
    """
    data = _load_all()
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
    data = _load_all()
    user_key = str(user_id)

    data[user_key] = {
        "size": str(size),
        "entry_price": str(entry_price),
    }

    _save_all(data)


def clear_user_position(user_id: int | str):
    """Clear a user's stored position."""
    data = _load_all()
    user_key = str(user_id)

    if user_key in data:
        del data[user_key]
        _save_all(data)
