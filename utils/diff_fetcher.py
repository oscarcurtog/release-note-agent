#!/usr/bin/env python3
"""Diff fetcher with MCP-first, REST fallback and guardrails.

Collect PR file changes and patch content, apply ignore rules and caps, and
return a structured DiffBundle. Raises DiffFetchError with typed codes.
"""

import logging
import re
from typing import Dict, List, Optional

from configs.config import Config
from .pr_data_source import PRDataSource, PRDataSourceError
from .diff_models import DiffFile, DiffBundle

logger = logging.getLogger(__name__)


class DiffFetchError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN", *, cause: Exception | None = None):
        super().__init__(message)
        self.code = code
        self.cause = cause


# Guardrails (defaults; can be made configurable later)
MAX_FILES = 200
MAX_DIFF_BYTES = 10 * 1024 * 1024  # 10MB

# Ignore patterns
IGNORE_DIRS_RE = re.compile(r"(^|/)(node_modules|vendor|dist|build|target|\.next|out|\.venv|__pycache__|\.git)/")
from configs.config import Config as _Cfg

IGNORE_EXTS = (
    ".min.js", ".min.css", ".map", ".lock", ".bundle",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", (
        # .svg handled by flag: if treated as text, do not filter by ext here
        ) if _Cfg.TREAT_SVG_AS_TEXT else ".svg",
    ".pdf", ".zip", ".bin",
)


def is_ignored_path(path: str) -> bool:
    if IGNORE_DIRS_RE.search(path):
        return True
    for ext in IGNORE_EXTS:
        if not ext:
            continue
        if path.endswith(ext):
            return True
    return False


def infer_change_type(path: str) -> str:
    lower = path.lower()
    if lower.startswith("docs/") or lower.endswith((".md", ".rst", ".adoc")):
        return "docs"
    if lower.startswith(("test/", "tests/")) or re.search(r"(_test\.|Test\.)", path):
        return "tests"
    if lower.endswith((".yml", ".yaml", ".json", ".toml", ".ini")) or lower.startswith((".github/", ".config/", "config/")):
        return "config"
    if lower.endswith((".csv", ".parquet", ".avro")):
        return "data"
    return "code"


def count_hunks(patch: Optional[str]) -> Optional[int]:
    if not patch:
        return None
    return len(re.findall(r"^@@", patch, flags=re.MULTILINE))


def summarize_file(diff_file: DiffFile) -> Optional[str]:
    if diff_file.is_binary:
        return None
    words_limit = 60
    summary = (
        f"{diff_file.status.capitalize()} {diff_file.filename} with {diff_file.additions} additions and "
        f"{diff_file.deletions} deletions."
    )
    if diff_file.hunk_count is not None:
        summary += f" {diff_file.hunk_count} hunks."
    # Keep it short; more heuristics can be added later
    return summary


class DiffFetcher:
    def __init__(self, data_source: Optional[PRDataSource] = None) -> None:
        self.data_source = data_source or PRDataSource()
        self._initialized = False
        self.timeout_s = Config.get_github_config().get("timeout_s", 30)

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.data_source.initialize()
            self._initialized = True

    def fetch(self, owner: str, repo: str, pr_number: int, base_sha: str, head_sha: str) -> DiffBundle:
        if not base_sha or not head_sha:
            raise DiffFetchError("Missing base/head SHA to compute diff", code="NOT_FOUND")

        self._ensure_initialized()

        try:
            files_json = self.data_source.get_pull_request_files(owner, repo, pr_number)
        except PRDataSourceError as e:
            raise DiffFetchError(f"Failed to list PR files: {e}", code=getattr(e, "code", "UNKNOWN"), cause=e)

        total_additions = 0
        total_deletions = 0
        total_changes = 0
        diff_files: List[DiffFile] = []
        diagnostics: List[str] = []
        truncated = False

        # Early file cap enforcement
        if len(files_json) > MAX_FILES:
            diagnostics.append(f"File cap hit: {len(files_json)} > {MAX_FILES}")
            truncated = True
            files_json = files_json[:MAX_FILES]

        # Determine if we need a unified diff
        need_unified = any(f.get("patch") in (None, "") for f in files_json)
        unified_map: Dict[str, str] = {}
        unified_total_bytes = 0

        if need_unified:
            try:
                unified_text = self._fetch_unified_diff(owner, repo, pr_number, base_sha, head_sha)
                unified_total_bytes = len(unified_text.encode("utf-8", errors="ignore"))
                if unified_total_bytes > MAX_DIFF_BYTES:
                    diagnostics.append(f"Unified diff size cap hit: {unified_total_bytes} bytes > {MAX_DIFF_BYTES}")
                    truncated = True
                    # We still proceed but do not attach large patches
                unified_map = self._split_unified_by_file(unified_text)
            except DiffFetchError as e:
                # Surface unified diff fetch issues but continue with available patches
                diagnostics.append(f"Unified diff unavailable: {e.code}")

        # Build files
        for f in files_json:
            filename = f.get("filename", "")
            if not filename or is_ignored_path(filename):
                continue

            status = f.get("status", "modified")
            additions = int(f.get("additions", 0))
            deletions = int(f.get("deletions", 0))
            changes = int(f.get("changes", additions + deletions))
            previous_filename = f.get("previous_filename")

            raw_patch = f.get("patch")
            is_binary = raw_patch is None
            patch: Optional[str] = None

            if not is_binary:
                patch = str(raw_patch)
            elif filename in unified_map:
                # Try to supplement with unified diff per-file section
                patch = unified_map.get(filename)
                is_binary = False if patch else True

            total_additions += additions
            total_deletions += deletions
            total_changes += changes

            diff_file = DiffFile(
                filename=filename,
                status=status,
                additions=additions,
                deletions=deletions,
                changes=changes,
                previous_filename=previous_filename,
                is_binary=is_binary,
                change_type=infer_change_type(filename),
                patch=patch,
                hunk_count=count_hunks(patch),
            )
            diff_file.summary = summarize_file(diff_file)
            diff_files.append(diff_file)

        bundle = DiffBundle(
            pr_number=pr_number,
            base_sha=base_sha,
            head_sha=head_sha,
            total_files=len(diff_files),
            total_additions=total_additions,
            total_deletions=total_deletions,
            total_changes=total_changes,
            truncated=truncated,
            files=diff_files,
            diagnostics=diagnostics,
        )
        return bundle

    def _fetch_unified_diff(self, owner: str, repo: str, pr_number: int, base_sha: str, head_sha: str) -> str:
        """Fetch unified diff via REST fallback endpoints.

        Try PR diff first, fallback to compare.
        """
        # Reuse existing REST client from data source if available
        client = getattr(self.data_source, "github_client", None)
        if client is None:
            try:
                from .github_fallback import GithubFallback
                client = GithubFallback()
            except Exception as e:
                raise DiffFetchError("REST client unavailable", code="UNKNOWN", cause=e)
        headers = {"Accept": "application/vnd.github.v3.diff"}

        import requests

        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        compare_url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"

        try:
            resp = client.session.get(pr_url, headers=headers, timeout=self.timeout_s)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (401, 403):
                raise DiffFetchError("Unauthorized", code="UNAUTHORIZED")
            if resp.status_code == 404:
                # Fallback to compare
                resp2 = client.session.get(compare_url, headers=headers, timeout=self.timeout_s)
                if resp2.status_code == 200:
                    return resp2.text
                if resp2.status_code in (401, 403):
                    raise DiffFetchError("Unauthorized", code="UNAUTHORIZED")
                if resp2.status_code == 404:
                    raise DiffFetchError("Not found", code="NOT_FOUND")
                if resp2.status_code == 429:
                    raise DiffFetchError("Rate limited", code="RATE_LIMIT")
                raise DiffFetchError(f"HTTP {resp2.status_code}", code="UNKNOWN")
            if resp.status_code == 429:
                raise DiffFetchError("Rate limited", code="RATE_LIMIT")
            raise DiffFetchError(f"HTTP {resp.status_code}", code="UNKNOWN")
        except requests.Timeout as e:
            raise DiffFetchError("Timeout", code="TIMEOUT", cause=e)
        except requests.ConnectionError as e:
            raise DiffFetchError("Network error", code="NETWORK", cause=e)

    def _split_unified_by_file(self, unified_text: str) -> Dict[str, str]:
        """Split unified diff into per-file patches by parsing 'diff --git' sections."""
        file_map: Dict[str, str] = {}
        if not unified_text:
            return file_map

        # Split by diff --git lines
        sections = re.split(r"^diff --git a/(.+) b/(.+)$", unified_text, flags=re.MULTILINE)
        # sections structure: [pre, filename1, body1, filename2, body2, ...]
        if len(sections) < 3:
            return file_map
        it = iter(sections[1:])
        # For each (old, new, body)
        for old, new, body in zip(it, it, it):
            key_new = new.strip()
            file_map[key_new] = body
            # Also store mapping for rename cases (so we can find by either name)
            key_old = old.strip()
            file_map.setdefault(key_old, body)
        return file_map

    def _infer_code(self, message: str) -> str:
        m = message.lower()
        if "timeout" in m:
            return "TIMEOUT"
        if "not found" in m or "404" in m:
            return "NOT_FOUND"
        if "unauthorized" in m or "401" in m or "403" in m:
            return "UNAUTHORIZED"
        if "429" in m or "rate limit" in m:
            return "RATE_LIMIT"
        if "network" in m or "connection" in m:
            return "NETWORK"
        return "UNKNOWN"


