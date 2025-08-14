#!/usr/bin/env python3
from __future__ import annotations

from hmac import compare_digest

from utils.release_notes_models import ReleaseNotesDraft


def idempotency_key(draft: ReleaseNotesDraft) -> str:
	repo = draft.repo or ""
	pr = draft.pr_number
	sha = draft.head_sha or ""
	if not repo or not pr or not sha:
		raise ValueError("Missing repo/pr/head_sha for idempotency key")
	# Canonical format: <owner>/<repo>#<pr_number>#<head_sha>
	return f"{repo}#{pr}#{sha}"


def is_same_key(a: str, b: str) -> bool:
	return bool(compare_digest(a or "", b or ""))
