#!/usr/bin/env python3
"""Persistence helpers for PR comment IDs (atomic, tolerant)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _path_for(key: str, root: str) -> Path:
    # Sanitize for Windows and POSIX: replace both '/' and os.sep
    safe_key = key.replace("/", "#").replace(os.sep, "#")
    return Path(root) / f"{safe_key}.id"


def save_comment_id(key: str, comment_id: int, root: str = ".cache/release_notes/comments") -> None:
    """Persist comment_id atomically for a given idempotency key.

    Uses fsync + atomic replace for durability across platforms.
    """
    path = _path_for(key, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = str(int(comment_id))
    # Write with fsync
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    # Atomic replace
    os.replace(tmp, path)


def load_comment_id(key: str, root: str = ".cache/release_notes/comments") -> Optional[int]:
    """Load persisted comment_id; return None if missing or invalid."""
    path = _path_for(key, root)
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return int(raw)
    except Exception:
        return None


def delete_comment_id(key: str, root: str = ".cache/release_notes/comments") -> None:
    """Delete the persisted id if present; ignore errors."""
    path = _path_for(key, root)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        return None


