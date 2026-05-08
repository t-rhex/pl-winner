"""Resolve the on-disk data directory.

Honors the ``PL_WINNER_DATA_DIR`` env var so containers / sandboxes can pin
caches to a writable mount. Falls back to ``<repo>/data`` for dev installs.
"""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("PL_WINNER_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def fpl_cache_dir() -> Path:
    return data_dir() / "fpl"


def predictions_db_path() -> Path:
    return data_dir() / "predictions.db"
