#!/usr/bin/env python3
"""PR comment upsert utilities (MCP-first, REST fallback).

This module manages a single preview comment per PR head SHA using HTML markers
and a persisted comment_id cache to enable idempotent updates across runs.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Optional, Tuple, Dict, Any, List

from configs.config import Config
from utils.pr_models import PRContext
from utils.comment_persistence import load_comment_id


logger = logging.getLogger(__name__)

MAX_GH_COMMENT_CHARS = Config.MAX_GH_COMMENT_CHARS


class CommenterError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN"):
        super().__init__(message)
        self.code = code


def _retryable(code: str) -> bool:
    return code in {"RATE_LIMIT", "NETWORK", "TIMEOUT"}


def _has_marker(body: str, marker: str) -> bool:
    return bool(body) and (marker in body)


class PRCommenter:
    def __init__(self, mcp_client, rest_client, *, marker_preview: str, marker_key: str):
        self.mcp_client = mcp_client
        self.rest_client = rest_client
        self.marker_preview = marker_preview
        self.marker_key = marker_key

    # ---- Internals: MCP/REST operations (thin wrappers) ----
    def _list_issue_comments(self, owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        try:
            if self.mcp_client and getattr(self.mcp_client, "list_issue_comments", None):
                return self.mcp_client.list_issue_comments(owner, repo, pr_number)
        except Exception as e:
            logger.debug(f"MCP list_issue_comments failed: {e}")
        # REST fallback
        if self.rest_client and getattr(self.rest_client, "list_issue_comments", None):
            return self.rest_client.list_issue_comments(owner, repo, pr_number)
        # Minimal REST via requests (fallback of fallback)
        from utils.github_fallback import GithubFallback, GithubApiError, GithubAuthError
        try:
            gh = GithubFallback()
            # GitHub API: GET /issues/{issue_number}/comments
            url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
            headers = {"Accept": "application/vnd.github+json"}
            resp = gh.session.get(url, headers=headers, timeout=Config.HTTP_TIMEOUT_S)
            if resp.status_code == 401:
                raise CommenterError("Unauthorized", code="UNAUTHORIZED")
            if resp.status_code == 403:
                raise CommenterError("Forbidden", code="UNAUTHORIZED")
            if resp.status_code == 429:
                raise CommenterError("Rate limited", code="RATE_LIMIT")
            if resp.status_code >= 400:
                raise CommenterError(f"HTTP {resp.status_code}")
            return resp.json()  # type: ignore[no-any-return]
        except (GithubApiError, GithubAuthError) as ge:
            code = "UNAUTHORIZED" if isinstance(ge, GithubAuthError) else "NETWORK"
            raise CommenterError(str(ge), code=code)

    def _create_issue_comment(self, owner: str, repo: str, pr_number: int, body: str) -> Dict[str, Any]:
        try:
            if self.mcp_client and getattr(self.mcp_client, "create_issue_comment", None):
                return self.mcp_client.create_issue_comment(owner, repo, pr_number, body)
        except Exception as e:
            logger.debug(f"MCP create_issue_comment failed: {e}")
        if self.rest_client and getattr(self.rest_client, "create_issue_comment", None):
            return self.rest_client.create_issue_comment(owner, repo, pr_number, body)
        from utils.github_fallback import GithubFallback, GithubApiError, GithubAuthError
        try:
            gh = GithubFallback()
            url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
            payload = {"body": body}
            headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json"}
            resp = gh.session.post(url, headers=headers, data=json.dumps(payload), timeout=Config.HTTP_TIMEOUT_S)
            if resp.status_code == 401:
                raise CommenterError("Unauthorized", code="UNAUTHORIZED")
            if resp.status_code == 403:
                raise CommenterError("Forbidden", code="UNAUTHORIZED")
            if resp.status_code >= 400:
                if resp.status_code == 429:
                    raise CommenterError("Rate limited", code="RATE_LIMIT")
                raise CommenterError(f"HTTP {resp.status_code}")
            return resp.json()
        except (GithubApiError, GithubAuthError) as ge:
            code = "UNAUTHORIZED" if isinstance(ge, GithubAuthError) else "NETWORK"
            raise CommenterError(str(ge), code=code)

    def _update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> Dict[str, Any]:
        try:
            if self.mcp_client and getattr(self.mcp_client, "update_issue_comment", None):
                return self.mcp_client.update_issue_comment(owner, repo, comment_id, body)
        except Exception as e:
            logger.debug(f"MCP update_issue_comment failed: {e}")
        if self.rest_client and getattr(self.rest_client, "update_issue_comment", None):
            return self.rest_client.update_issue_comment(owner, repo, comment_id, body)
        from utils.github_fallback import GithubFallback, GithubApiError, GithubAuthError
        try:
            gh = GithubFallback()
            url = f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}"
            payload = {"body": body}
            headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json"}
            resp = gh.session.patch(url, headers=headers, data=json.dumps(payload), timeout=Config.HTTP_TIMEOUT_S)
            if resp.status_code == 401:
                raise CommenterError("Unauthorized", code="UNAUTHORIZED")
            if resp.status_code == 403:
                raise CommenterError("Forbidden", code="UNAUTHORIZED")
            if resp.status_code == 409:
                raise CommenterError("Conflict", code="CONFLICT")
            if resp.status_code == 404:
                raise CommenterError("Not found", code="NOT_FOUND")
            if resp.status_code >= 400:
                if resp.status_code == 429:
                    raise CommenterError("Rate limited", code="RATE_LIMIT")
                raise CommenterError(f"HTTP {resp.status_code}")
            return resp.json()
        except (GithubApiError, GithubAuthError) as ge:
            code = "UNAUTHORIZED" if isinstance(ge, GithubAuthError) else "NETWORK"
            raise CommenterError(str(ge), code=code)

    # ---- Public API ----
    def find_existing_comment(self, pr: PRContext, key: str) -> Optional[int]:
        """Find a previously created comment ID for this key.

        Strategy:
          1) Try persisted comment_id
          2) Else list and search for markers
        """
        # 1) persisted id
        persisted = load_comment_id(key, root=Config.COMMENT_CACHE_ROOT)
        owner, repo = pr.repo.split("/")
        if persisted:
            try:
                comments = self._list_issue_comments(owner, repo, pr.pr.number)
                for c in comments:
                    if c.get("id") == persisted:
                        body = c.get("body", "") or ""
                        if _has_marker(body, self.marker_key) or _has_marker(body, self.marker_preview):
                            return persisted
            except CommenterError:
                # If listing fails, we cannot validate; fall through to search
                pass
        # 2) list and search
        comments = self._list_issue_comments(owner, repo, pr.pr.number)
        for c in comments:
            body = c.get("body", "") or ""
            if _has_marker(body, self.marker_key) or _has_marker(body, self.marker_preview):
                return int(c.get("id"))
        return None

    def _apply_truncation(self, body: str) -> str:
        if len(body) <= MAX_GH_COMMENT_CHARS:
            return body
        footer = "\n\n---\n_Comment truncated to fit GitHub limits. View full notes in artifact/cache or build logs._"
        head = body[: max(0, MAX_GH_COMMENT_CHARS - len(footer))]
        return head + footer

    def _with_markers(self, body: str) -> str:
        return f"{self.marker_preview}\n{self.marker_key}\n\n" + body

    def _retry(self, func, *args, **kwargs):
        max_attempts = 1 + Config.COMMENT_RETRY_MAX
        base = Config.COMMENT_RETRY_BASE_SLEEP
        attempt = 0
        last_err: Optional[CommenterError] = None
        while attempt < max_attempts:
            try:
                return func(*args, **kwargs)
            except CommenterError as ce:
                last_err = ce
                if not _retryable(ce.code):
                    break
                # backoff + jitter
                delay = base * (2 ** attempt) + random.random() * 0.1
                time.sleep(delay)
                attempt += 1
        if last_err:
            raise last_err
        raise CommenterError("Unknown failure", code="UNKNOWN")

    def upsert_preview_comment(self, pr: PRContext, markdown: str, key: str) -> Tuple[int, str, bool]:
        """Create or update preview comment for the PR and key.

        Returns (comment_id, html_url, created_bool).
        """
        owner, repo = pr.repo.split("/")
        pr_number = pr.pr.number
        body = self._apply_truncation(markdown)
        body = self._with_markers(body)

        existing_id = self.find_existing_comment(pr, key)
        if existing_id is not None:
            # Update existing
            try:
                updated = self._retry(self._update_issue_comment, owner, repo, existing_id, body)
                return int(updated.get("id", existing_id)), updated.get("html_url", ""), False
            except CommenterError as ce:
                if ce.code == "CONFLICT":
                    # Re-list and retry once
                    comments = self._list_issue_comments(owner, repo, pr_number)
                    for c in comments:
                        b = c.get("body", "") or ""
                        if _has_marker(b, self.marker_key) and c.get("id"):
                            updated = self._retry(self._update_issue_comment, owner, repo, c["id"], body)
                            return int(updated.get("id", c["id"])), updated.get("html_url", ""), False
                if ce.code == "NOT_FOUND":
                    # Comment disappeared between list and update; create a new one
                    created = self._retry(self._create_issue_comment, owner, repo, pr_number, body)
                    return int(created.get("id")), created.get("html_url", ""), True
                # Fall through to create
        # Create new
        created = self._retry(self._create_issue_comment, owner, repo, pr_number, body)
        return int(created.get("id")), created.get("html_url", ""), True


    def publish_final_comment(self, pr: PRContext, markdown_final: str, key: str) -> Tuple[int, str]:
        """Publish a FINAL comment. Always creates a new comment with FINAL markers.

        Does not modify preview comments.
        Returns (comment_id, html_url).
        """
        owner, repo = pr.repo.split("/")
        pr_number = pr.pr.number
        body = self._apply_truncation(markdown_final)
        # Transform preview marker to FINAL for safety if caller passed preview marker
        final_preview_marker = self.marker_preview.replace("PREVIEW", "FINAL")
        body = f"{final_preview_marker}\n{self.marker_key}\n\n" + body
        created = self._retry(self._create_issue_comment, owner, repo, pr_number, body)
        return int(created.get("id")), created.get("html_url", "")

    def post_feedback(self, owner: str, repo: str, pr_number: int, message: str) -> None:
        """Post a best-effort feedback comment with neutral markers.

        Swallows exceptions; meant for user-facing short diagnostics.
        """
        try:
            neutral_preview = self.marker_preview
            neutral_key = self.marker_key
            body = f"{neutral_preview}\n{neutral_key}\n\n{message}"
            self._create_issue_comment(owner, repo, pr_number, body)
        except Exception:
            return None


