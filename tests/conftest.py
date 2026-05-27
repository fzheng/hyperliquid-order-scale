"""Shared fixtures."""
import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def storage_module(tmp_path, monkeypatch):
    """Reload core.storage with DATA_DIR pointed at a tmp_path.

    Returns the freshly-reloaded module so tests get isolated JSON files.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import core.storage as storage
    importlib.reload(storage)
    yield storage
    # Reset to a fresh import after the test so subsequent tests don't
    # see the tmp_path that no longer exists.
    importlib.reload(storage)
