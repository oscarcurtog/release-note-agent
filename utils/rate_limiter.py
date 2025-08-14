#!/usr/bin/env python3
"""Simple file-based rate limiter for PR commands (Windows/CI friendly)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


def _safe_key(s: str) -> str:
    return s.replace("/", "#").replace(os.sep, "#")


def rate_limit_key(repo: str, pr_number: int) -> str:
    return _safe_key(f"{repo}#pr#{pr_number}")


@dataclass
class RateLimitResult:
    allowed: bool
    reason: str
    remaining: int
    reset_in_s: int


def _read_state(path: Path) -> Tuple[int, int]:
    try:
        if not path.exists():
            return 0, 0
        data = json.loads(path.read_text(encoding="utf-8"))
        start = int(data.get("start", 0))
        count = int(data.get("count", 0))
        return start, count
    except Exception:
        return 0, 0


def _write_state(path: Path, start: int, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps({"start": start, "count": count}, separators=(",", ":"))
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def check_and_update_rate_limit(
    key: str,
    *,
    max_attempts: int,
    window_seconds: int,
    root: str = ".cache/release_notes/commands",
) -> RateLimitResult:
    now = int(time.time())
    safe = _safe_key(key)
    path = Path(root) / f"{safe}.rl.json"
    start, count = _read_state(path)

    if start <= 0 or now - start >= window_seconds:
        # Start a new window
        _write_state(path, now, 1)
        return RateLimitResult(True, "new_window", max_attempts - 1, window_seconds)

    # Within window
    if count < max_attempts:
        _write_state(path, start, count + 1)
        remaining = max_attempts - (count + 1)
        return RateLimitResult(True, "ok", remaining, max(0, window_seconds - (now - start)))

    # Denied
    reset_in = max(1, window_seconds - (now - start))
    return RateLimitResult(False, "rate_limited", 0, reset_in)


