#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import List

from utils.release_notes_models import ReleaseNotesDraft


class JSONSanitizerError(Exception):
	def __init__(self, message: str, code: str = "SANITIZE_ERROR") -> None:
		super().__init__(message)
		self.code = code


# --- Private helpers ---

def _strip_fences(text: str) -> str:
	return re.sub(r"```[a-zA-Z]*\n|```", "", text)


def _remove_control_chars(text: str) -> str:
	return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", text)


def _largest_braced_region(text: str) -> str | None:
	stack: List[int] = []
	best = None
	best_len = 0
	for i, ch in enumerate(text):
		if ch == '{':
			stack.append(i)
		elif ch == '}' and stack:
			start = stack.pop()
			cand = text[start:i+1]
			if len(cand) > best_len:
				best = cand
				best_len = len(cand)
	return best


def _fix_trailing_commas(s: str) -> str:
	return re.sub(r",\s*([}\]])", r"\1", s)


def _smart_quotes(s: str) -> str:
	return s.replace("“", '"').replace("”", '"').replace("’", "'")


# --- Public API ---

def extract_json_objects(raw_text: str) -> List[str]:
	"""Return candidate JSON object strings found in raw_text, most-likely first."""
	if not raw_text:
		return []
	text = _remove_control_chars(_strip_fences(raw_text))
	cands: List[str] = []
	# Prefer largest braced region
	largest = _largest_braced_region(text)
	if largest:
		cands.append(largest)
	# Fallback: naive scan for first and last braces
	first = text.find('{')
	last = text.rfind('}')
	if first != -1 and last != -1 and last > first:
		frag = text[first:last+1]
		if frag not in cands:
			cands.append(frag)
	# Entire text as last resort
	if text not in cands:
		cands.append(text)
	return cands


def minimal_json_repairs(s: str) -> str:
	"""Apply minimal, safe repairs without inventing content."""
	s = _smart_quotes(s)
	s = _fix_trailing_commas(s)
	return s.strip()


def extract_and_validate_release_notes(raw_text: str) -> ReleaseNotesDraft:
	candidates = extract_json_objects(raw_text)
	if not candidates:
		raise JSONSanitizerError("No JSON object candidates found", code="NO_JSON")
	last_error: Exception | None = None
	for cand in candidates:
		try:
			fixed = minimal_json_repairs(cand)
			data = json.loads(fixed)
			return ReleaseNotesDraft.model_validate(data)
		except json.JSONDecodeError as e:
			last_error = e
			continue
		except Exception as e:
			# Pydantic validation failure etc.
			raise JSONSanitizerError(str(e), code="VALIDATION")
	# If we exhausted candidates with decode errors
	raise JSONSanitizerError(str(last_error or "JSON decode error"), code="JSON_DECODE")
