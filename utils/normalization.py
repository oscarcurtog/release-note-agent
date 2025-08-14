#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import List, Tuple, Dict, Iterable

from utils.release_notes_models import ReleaseNotesDraft, ReleaseNoteItem
from configs.config import Config


def _collapse_spaces(s: str) -> str:
	if not s:
		return s
	s = s.strip()
	if Config.NORMALIZE_COLLAPSE_SPACES:
		s = re.sub(r"\s+", " ", s)
	return s


def _lower_or_none(s):
	return s.lower() if isinstance(s, str) else s


def _norm_list_str(values: Iterable[str]) -> List[str]:
	out = []
	for v in values or []:
		vv = _collapse_spaces(str(v))
		if vv:
			out.append(vv)
	# dedupe + sort
	return sorted(list(dict.fromkeys(out)))


def _key_for_item(it: ReleaseNoteItem) -> Tuple[str, str, str, int, int]:
	files = _norm_list_str(it.files or [])
	shas = _norm_list_str(it.commit_shas or [])
	return (_lower_or_none(it.type or ""), _lower_or_none(it.scope or ""), _collapse_spaces(it.title or ""), hash(tuple(files)), hash(tuple(shas)))


def _merge_items(items: List[ReleaseNoteItem]) -> ReleaseNoteItem:
	base = items[0]
	breaking = any(bool(i.breaking) for i in items)
	confidence = max([i.confidence for i in items if i.confidence is not None] or [None])
	issue_refs = _norm_list_str(sum([i.issue_refs or [] for i in items], []))
	components = _norm_list_str(sum([i.components or [] for i in items], []))
	files = _norm_list_str(sum([i.files or [] for i in items], []))
	shas = _norm_list_str(sum([i.commit_shas or [] for i in items], []))
	return ReleaseNoteItem(
		type=_lower_or_none(base.type),
		title=_collapse_spaces(base.title),
		details=_collapse_spaces(base.details) if base.details else None,
		scope=_lower_or_none(base.scope) if base.scope else None,
		breaking=breaking,
		confidence=confidence,
		issue_refs=issue_refs or None,
		components=components or None,
		files=files or None,
		commit_shas=shas or None,
	)


def _sort_items(items: List[ReleaseNoteItem], *, section: str) -> List[ReleaseNoteItem]:
	scope_order = ["api","ui","core","infra","build","data","docs","tests","config","deps","release", None]
	type_order = ["feature","security","perf","refactor","fix","docs","test","build","ci","chore","style","revert"]
	def key(it: ReleaseNoteItem):
		so = scope_order.index(_lower_or_none(it.scope)) if _lower_or_none(it.scope) in scope_order else len(scope_order)
		to = type_order.index(_lower_or_none(it.type)) if _lower_or_none(it.type) in type_order else len(type_order)
		title_key = it.title.casefold() if Config.NORMALIZE_SORT_CASEFOLD and it.title else (it.title or "")
		if section == "breaking_changes":
			# ignore type for breaking section ordering
			return (so, title_key)
		return (so, to, title_key)
	return sorted(items, key=key)


def normalize_release_notes(draft: ReleaseNotesDraft) -> ReleaseNotesDraft:
	# Normalize and dedupe each section
	sections = ["highlights", "fixes", "docs", "breaking_changes"]
	new_data = draft.model_dump()
	for sec in sections:
		raw: List[dict] = [i for i in new_data.get(sec, [])]
		items = [ReleaseNoteItem.model_validate(i) for i in raw]
		# Canonicalize fields
		canon = []
		for it in items:
			canon.append(
				ReleaseNoteItem(
					type=_lower_or_none(it.type),
					title=_collapse_spaces(it.title),
					details=_collapse_spaces(it.details) if it.details else None,
					scope=_lower_or_none(it.scope) if it.scope else None,
					breaking=bool(it.breaking),
					confidence=it.confidence,
					issue_refs=_norm_list_str(it.issue_refs or []) or None,
					components=_norm_list_str(it.components or []) or None,
					files=_norm_list_str(it.files or []) or None,
					commit_shas=_norm_list_str(it.commit_shas or []) or None,
				)
			)
		# Group by stable key
		groups: Dict[Tuple[str,str,str,int,int], List[ReleaseNoteItem]] = {}
		for it in canon:
			k = _key_for_item(it)
			groups.setdefault(k, []).append(it)
		merged = [_merge_items(v) for v in groups.values()]
		new_data[sec] = [m.model_dump() for m in _sort_items(merged, section=sec)]
	# Ensure optional lists exist
	new_data.setdefault("deprecations", [])
	new_data.setdefault("upgrade_notes", [])
	new_data.setdefault("known_issues", [])
	# Return new instance
	return ReleaseNotesDraft.model_validate(new_data)
