#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Dict, Any, Tuple, List

from utils.pr_models import PRContext
from utils.diff_processor import ProcessedDiff
from utils.release_notes_models import ReleaseNotesDraft
from utils.schema_utils import to_json_schema


def _render_template(template: str, mapping: Dict[str, str]) -> str:
	text = template
	for key, value in mapping.items():
		text = text.replace(f"{{{{ {key} }}}}", value)
	return text


def _bulleted(lines: List[str], *, max_lines: int = 10) -> str:
	if not lines:
		return "- none"
	out = []
	for i, line in enumerate(lines[:max_lines]):
		line_clean = str(line).replace("\r", " ").replace("\n", " ")
		out.append(f"- {line_clean}")
	return "\n".join(out)


def build_single_chunk_prompt(pr: PRContext, diff: ProcessedDiff) -> Tuple[str, Dict[str, Any]]:
	"""Build prompt text for a single diff chunk.

	Returns the prompt text and meta info for logging.
	"""
	if not diff.chunks:
		raise ValueError("No diff chunks available for prompt")
	chunk = diff.chunks[0]
	# Assemble context
	labels = [label.name for label in pr.pr.labels] if getattr(pr.pr, "labels", None) else []
	labels_csv = ", ".join(labels)[:500]
	degradation = getattr(diff, "degradation", None)
	degradation_reason = getattr(diff, "degradation_reason", None)
	truncated = bool(getattr(diff, "truncated", False))
	diagnostics = getattr(diff, "diagnostics", []) or []
	diagnostics_txt = _bulleted(diagnostics, max_lines=10)
	# Diff chunk text: concatenate trimmed patches or summaries per file
	parts = []
	for pf in chunk.files:
		if pf.patch_trimmed:
			parts.append(f"--- {pf.path} ({pf.change_type})\n{pf.patch_trimmed}")
		else:
			parts.append(f"--- {pf.path} ({pf.change_type})\n# no patch available; summary: {pf.summary}")
	diff_text = "\n\n".join(parts)
	# JSON schema
	schema_dict = to_json_schema(ReleaseNotesDraft)
	schema_json = json.dumps(schema_dict, separators=(",", ":"))
	# Load template
	with open("prompts/release_notes.prompt", "r", encoding="utf-8") as f:
		template = f.read()
	mapping = {
		"repo": pr.repo,
		"pr_number": str(pr.pr.number),
		"head_sha": pr.pr.head_sha or "",
		"author": pr.pr.user.login,
		"pr_title": pr.pr.title,
		"labels_csv": labels_csv,
		"is_draft": str(pr.pr.is_draft),
		"base_ref": pr.pr.base_ref or "",
		"head_ref": pr.pr.head_ref or "",
		"degradation": str(degradation),
		"degradation_reason": str(degradation_reason or ""),
		"truncated": str(truncated),
		"diagnostics_bulleted": diagnostics_txt,
		"json_schema": schema_json,
		"diff_chunk": diff_text,
	}
	prompt = _render_template(template, mapping)
	meta = {
		"repo": pr.repo,
		"pr": pr.pr.number,
		"head": pr.pr.head_sha,
		"files_in_chunk": chunk.files_count,
		"prompt_len": len(prompt),
	}
	return prompt, meta
