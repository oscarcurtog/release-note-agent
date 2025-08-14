#!/usr/bin/env python3
from __future__ import annotations

import os
import textwrap
from typing import List

from utils.release_notes_models import ReleaseNotesDraft, ReleaseNoteItem
from configs.config import Config


def escape_md(s: str) -> str:
	if not s:
		return s
	for ch in ["*", "_", "`", "|"]:
		s = s.replace(ch, f"\\{ch}")
	return s


def _wrap(text: str, width: int = 110) -> str:
	return "\n".join(textwrap.wrap(text, width=width, replace_whitespace=False, break_long_words=False))


def bullets(items: List[ReleaseNoteItem]) -> str:
	out_lines: List[str] = []
	for it in items or []:
		scope_suffix = f" _(scope: {escape_md(it.scope)})_" if it.scope else ""
		breaking_suffix = " **(breaking)**" if it.breaking else ""
		confidence_suffix = f" — confidence {it.confidence:.2f}" if it.confidence is not None else ""
		line = f"- **[{escape_md(it.type)}]** {escape_md(it.title)}{scope_suffix}{breaking_suffix}{confidence_suffix}"
		out_lines.append(line)
		if it.details:
			out_lines.append("  " + _wrap(escape_md(it.details)))
		# compact refs line
		parts = []
		if it.issue_refs:
			parts.append("refs: " + ", ".join(escape_md(r) for r in it.issue_refs))
		if it.components:
			parts.append("comp: " + ", ".join(escape_md(c) for c in it.components))
		if it.files:
			parts.append("files: " + ", ".join(escape_md(f) for f in it.files[:5]))
		if parts:
			compact = " · ".join(parts)
			out_lines.append("  " + _wrap(compact))
	return "\n".join(out_lines)


def bullet_lines(lines: List[str]) -> str:
	return "\n".join("- " + _wrap(escape_md(line)) for line in (lines or []))


def render_markdown(draft: ReleaseNotesDraft, *, mode: str = "preview") -> str:
	# Load template
	tpl_path = os.path.join("rendering", "release_notes_md.j2")
	with open(tpl_path, "r", encoding="utf-8") as f:
		tpl = f.read()
	# Header label adjustment
	header = "Release Notes" if mode == "final" else "Release Notes (Preview)"
	tpl = tpl.replace("# Release Notes (Preview)", f"# {header}")
	# Prepare mapping
	mapping = {
		"repo": draft.repo or "",
		"pr_number": str(draft.pr_number or ""),
		"head_sha": draft.head_sha or "",
		"schema_version": draft.schema_version,
		"confidence_overall": f"{draft.confidence_overall:.2f}" if draft.confidence_overall is not None else "n/a",
		"highlights": draft.highlights,
		"fixes": draft.fixes,
		"docs": draft.docs,
		"breaking_changes": draft.breaking_changes,
		"deprecations": draft.deprecations,
		"upgrade_notes": draft.upgrade_notes,
		"known_issues": draft.known_issues or [],
	}
	# Simple block removal for empty sections
	def block(name: str, content: str) -> str:
		marker = f"{{% if {name} %}}"
		end = "{% endif %}"
		if mapping.get(name):
			return tpl
		# Remove the block entirely
		start_idx = tpl.find(marker)
		if start_idx == -1:
			return tpl
		end_idx = tpl.find(end, start_idx)
		if end_idx != -1:
			return tpl[:start_idx] + tpl[end_idx+len(end):]
		return tpl
	
	# Replace blocks for each section
	for sec in ["highlights","breaking_changes","fixes","docs","deprecations","upgrade_notes","known_issues"]:
		tpl = block(sec, tpl)
	# Replace variables and function calls
	tpl = tpl.replace("{{ repo }}", escape_md(mapping["repo"]))
	tpl = tpl.replace("{{ pr_number }}", mapping["pr_number"])  # number
	tpl = tpl.replace("{{ head_sha }}", escape_md(mapping["head_sha"]))
	tpl = tpl.replace("{{ schema_version }}", escape_md(mapping["schema_version"]))
	tpl = tpl.replace("{{ confidence_overall or \"n/a\" }}", mapping["confidence_overall"])  # safety
	# Render bullets
	tpl = tpl.replace("{{ bullets(highlights) }}", bullets(mapping["highlights"]))
	tpl = tpl.replace("{{ bullets(breaking_changes) }}", bullets(mapping["breaking_changes"]))
	tpl = tpl.replace("{{ bullets(fixes) }}", bullets(mapping["fixes"]))
	tpl = tpl.replace("{{ bullets(docs) }}", bullets(mapping["docs"]))
	tpl = tpl.replace("{{ bullets(deprecations) }}", bullets(mapping["deprecations"]))
	tpl = tpl.replace("{{ bullet_lines(upgrade_notes) }}", bullet_lines(mapping["upgrade_notes"]))
	tpl = tpl.replace("{{ bullet_lines(known_issues) }}", bullet_lines(mapping["known_issues"]))
	# If everything empty, render placeholder
	if not any([mapping["highlights"], mapping["fixes"], mapping["docs"], mapping["breaking_changes"], mapping["deprecations"], mapping["upgrade_notes"], mapping["known_issues"]]):
		if Config.RENDER_EMPTY_PLACEHOLDER:
			tpl += "\nNo user-facing changes detected.\n"
	return tpl
