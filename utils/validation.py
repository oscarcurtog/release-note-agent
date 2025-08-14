#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Tuple, Optional
from pydantic import ValidationError

from utils.release_notes_models import ReleaseNotesDraft
from configs.config import Config


class ValidationCode:
	OK = "OK"
	STRUCTURE = "STRUCTURE"
	FIELDS = "FIELDS"
	EMPTY = "EMPTY"


ValidationResult = Tuple[bool, str]


def _all_sections_empty(data: Dict[str, Any]) -> bool:
	sections = [
		"highlights",
		"fixes",
		"docs",
		"breaking_changes",
		"deprecations",
		"upgrade_notes",
		"known_issues",
	]
	for key in sections:
		val = data.get(key)
		if isinstance(val, list) and len(val) > 0:
			return False
		if key in ("upgrade_notes", "known_issues") and isinstance(val, list) and len(val) > 0:
			return False
	return True


def validate_release_notes_payload(data: Dict[str, Any]) -> Tuple[ValidationResult, Optional[ReleaseNotesDraft], str]:
	try:
		model = ReleaseNotesDraft.model_validate(data)
		if Config.EMPTY_SECTIONS_ERROR and _all_sections_empty(data):
			return (False, ValidationCode.EMPTY), None, "All sections empty"
		return (True, ValidationCode.OK), model, ""
	except ValidationError as e:
		msg = str(e)
		# Heuristic mapping
		low = msg.lower()
		code = ValidationCode.FIELDS
		if "extra fields not permitted" in low or "type=extra_forbidden" in low:
			code = ValidationCode.STRUCTURE
		return (False, code), None, msg
	except Exception as e:
		return (False, ValidationCode.STRUCTURE), None, str(e)
