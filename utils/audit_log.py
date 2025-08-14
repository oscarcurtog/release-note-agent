#!/usr/bin/env python3
"""Append-only audit logs for manual publish attempts."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict


def audit_publish_attempt(
    repo: str,
    pr_number: int,
    actor: str,
    association: str,
    result: str,
    details: Dict,
    root: str = ".cache/release_notes/audit",
) -> None:
    """Append a single JSON line with safe metadata.

    Fields: ts, repo, pr, actor, association, result, details
    """
    path = Path(root) / f"{repo.replace('/', '#')}#pr#{pr_number}.audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": int(time.time()),
        "repo": repo,
        "pr": pr_number,
        "actor": actor or "",
        "association": (association or "").upper(),
        "result": result,
        "details": details or {},
    }
    line = json.dumps(record, separators=(",", ":")) + "\n"
    # Simple append; fsync for durability
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


