#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from typing import Optional, Tuple

from configs.config import Config


class CacheEntry:
	def __init__(self, key: str, json_path: str, md_path: str) -> None:
		self.key = key
		self.json_path = json_path
		self.md_path = md_path


class CacheBackend:
	def __init__(self, root_dir: str = None) -> None:
		self.root_dir = root_dir or Config.CACHE_ROOT
		os.makedirs(self.root_dir, exist_ok=True)
		self.atomic = bool(getattr(Config, "CACHE_ATOMIC_WRITES", True))

	def key_to_paths(self, key: str) -> CacheEntry:
		base = os.path.join(self.root_dir, key.replace("/", "_"))
		return CacheEntry(key, base + ".json", base + ".md")

	def get(self, key: str) -> Optional[Tuple[str, str]]:
		entry = self.key_to_paths(key)
		if not (os.path.exists(entry.json_path) and os.path.exists(entry.md_path)):
			# Corrupted or miss
			self.invalidate(key)
			return None
		try:
			with open(entry.json_path, "r", encoding="utf-8") as fj:
				j = fj.read()
			with open(entry.md_path, "r", encoding="utf-8") as fm:
				m = fm.read()
			return j, m
		except Exception:
			# treat as miss and invalidate
			self.invalidate(key)
			return None

	def put(self, key: str, json_text: str, md_text: str) -> None:
		entry = self.key_to_paths(key)
		os.makedirs(self.root_dir, exist_ok=True)
		if not self.atomic:
			with open(entry.json_path, "w", encoding="utf-8") as fj:
				fj.write(json_text)
			with open(entry.md_path, "w", encoding="utf-8") as fm:
				fm.write(md_text)
			return
		# Atomic via temp files and rename
		for path, content in ((entry.json_path, json_text), (entry.md_path, md_text)):
			dirname = os.path.dirname(path)
			tmp_fd, tmp_path = tempfile.mkstemp(dir=dirname, prefix=".tmp_", suffix=os.path.splitext(path)[1])
			with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
				f.write(content)
				f.flush()
				os.fsync(f.fileno())
			os.replace(tmp_path, path)

	def invalidate(self, key: str) -> None:
		entry = self.key_to_paths(key)
		for path in (entry.json_path, entry.md_path):
			try:
				if os.path.exists(path):
					os.remove(path)
			except Exception:
				pass
