#!/usr/bin/env python3
"""Lightweight parser for /release-notes commands in PR comments.

Parses user PR comments conservatively, ignoring code fences, block quotes,
and inline code spans. Currently supports only the 'publish' command.
"""

from __future__ import annotations

from typing import Optional, Dict


SUPPORTED = {"publish"}


def _strip_inline_code_spans(line: str) -> str:
    """Remove inline code spans delimited by backticks from a single line.

    This avoids matching commands that appear inside inline code.
    """
    if not line or "`" not in line:
        return line
    out_chars = []
    in_code = False
    for ch in line:
        if ch == "`":
            in_code = not in_code
            continue
        if not in_code:
            out_chars.append(ch)
    return "".join(out_chars)


def parse_release_notes_command(body: str) -> Optional[Dict]:
    """Parse a PR comment body and return a command mapping if present.

    Rules:
      - Match lines with '/release-notes publish' (case-insensitive)
      - Ignore code fences and quoted blocks
      - Ignore commands inside inline code
      - Accept leading/trailing whitespace
    """
    if not body:
        return None

    target = "/release-notes publish"
    in_fence = False

    for raw in body.splitlines():
        line = raw.rstrip("\r\n")
        stripped = line.strip()

        # Track fenced code blocks (```) conservatively
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        # Skip block quotes
        if stripped.startswith(">"):
            continue

        cleaned = _strip_inline_code_spans(stripped)
        if cleaned.casefold() == target.casefold():
            return {"cmd": "publish"}

    return None


