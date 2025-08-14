#!/usr/bin/env python3
"""Authorization helpers for manual publish commands."""

from __future__ import annotations

import os
from typing import Set


def _load_allowed_roles() -> Set[str]:
    raw = os.getenv("ALLOWED_PUBLISH_ROLES", "OWNER,MEMBER,COLLABORATOR")
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    return set(parts or ["OWNER", "MEMBER", "COLLABORATOR"])  # default


ALLOWED_ASSOCIATIONS = _load_allowed_roles()


def is_authorized(association: str) -> bool:
    """Return True if the association is allowed (case-insensitive)."""
    if not association:
        return False
    return association.strip().upper() in ALLOWED_ASSOCIATIONS


def decision_reason(association: str) -> str:
    """Human-friendly reason for decisions used in audit or feedback."""
    if not association:
        return "No association provided"
    up = association.strip().upper()
    if up in ALLOWED_ASSOCIATIONS:
        return f"Authorized: {up}"
    allowed = ", ".join(sorted(ALLOWED_ASSOCIATIONS))
    return f"Not authorized: {up}. Allowed roles: {allowed}."


