#!/usr/bin/env python3
"""Publish final release notes to GitHub Releases (MCP-first, REST fallback).

This module provides a small wrapper for creating and updating release bodies,
with size validation, backups, and typed errors. It prefers MCP tools if
available, and falls back to REST using the existing GitHub session.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

from configs.config import Config


class ReleasePublishError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN"):
        super().__init__(message)
        self.code = code


@dataclass
class ReleaseInfo:
    id: int
    tag_name: str
    html_url: str
    draft: bool
    prerelease: bool
    target_commitish: Optional[str]


class ReleasePublisher:
    def __init__(self, mcp_client, rest_client, *, backups_root: str, body_max_chars: int, timeout_s: int):
        self.mcp_client = mcp_client
        self.rest_client = rest_client
        self.backups_root = backups_root
        self.body_max_chars = body_max_chars
        self.timeout_s = timeout_s

    # -------- Public API --------
    def get_by_tag(self, owner: str, repo: str, tag: str) -> Optional[ReleaseInfo]:
        # TODO: MCP integration if tools exist
        return self._rest_get_by_tag(owner, repo, tag)

    def get_by_id(self, owner: str, repo: str, release_id: int) -> Dict[str, Any]:
        """Return raw release JSON by id or raise NOT_FOUND.

        REST: GET /repos/{owner}/{repo}/releases/{id}
        """
        from utils.github_fallback import GithubFallback
        gh = GithubFallback()
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}"
        data = self._request(gh, "GET", url)
        if data is None:
            raise ReleasePublishError("Release not found", code="NOT_FOUND")
        return data

    def create_release(
        self,
        owner: str,
        repo: str,
        tag: str,
        body: str,
        *,
        name: Optional[str] = None,
        commitish: Optional[str] = None,
        draft: bool = False,
        prerelease: bool = False,
    ) -> ReleaseInfo:
        self._validate_body(body)
        return self._rest_create(owner, repo, tag, body, name=name or tag, commitish=commitish, draft=draft, prerelease=prerelease)

    def update_release(self, owner: str, repo: str, release_id: int, body: str, *, name: Optional[str] = None) -> ReleaseInfo:
        self._validate_body(body)
        return self._rest_update(owner, repo, release_id, body, name=name)

    def backup_existing_body(self, owner: str, repo: str, release: ReleaseInfo, body_text: str) -> None:
        """Backup the current release body to a timestamped file.

        Caller must provide the current body text to store.
        """
        safe_owner = owner.replace("/", "#").replace(os.sep, "#")
        safe_repo = repo.replace("/", "#").replace(os.sep, "#")
        safe_tag = (release.tag_name or "untagged").replace("/", "#").replace(os.sep, "#")
        ts = int(time.time())
        fname = f"{safe_owner}#{safe_repo}#{release.id}-{safe_tag}-{ts}.md"
        path = os.path.join(self.backups_root, fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body_text or "")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _validate_body(self, body: str) -> None:
        if body is None:
            raise ReleasePublishError("Empty release body", code="VALIDATION")
        if len(body) == 0:
            raise ReleasePublishError("Empty release body", code="VALIDATION")
        if len(body) > self.body_max_chars:
            raise ReleasePublishError(
                f"Release body exceeds limit: len={len(body)} max={self.body_max_chars}",
                code="VALIDATION",
            )

    # -------- REST fallback --------
    def _rest_get_by_tag(self, owner: str, repo: str, tag: str) -> Optional[ReleaseInfo]:
        from utils.github_fallback import GithubFallback
        gh = GithubFallback()
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
        resp = self._request(gh, "GET", url)
        if resp is None:
            return None
        data = resp
        return ReleaseInfo(
            id=int(data.get("id")),
            tag_name=data.get("tag_name", tag),
            html_url=data.get("html_url", ""),
            draft=bool(data.get("draft", False)),
            prerelease=bool(data.get("prerelease", False)),
            target_commitish=data.get("target_commitish"),
        )

    def _rest_create(
        self,
        owner: str,
        repo: str,
        tag: str,
        body: str,
        *,
        name: Optional[str] = None,
        commitish: Optional[str] = None,
        draft: bool = False,
        prerelease: bool = False,
    ) -> ReleaseInfo:
        from utils.github_fallback import GithubFallback
        gh = GithubFallback()
        url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        payload = {
            "tag_name": tag,
            "name": name or tag,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
        }
        if commitish:
            payload["target_commitish"] = commitish
        data = self._request(gh, "POST", url, payload)
        return ReleaseInfo(
            id=int(data.get("id")),
            tag_name=data.get("tag_name", tag),
            html_url=data.get("html_url", ""),
            draft=bool(data.get("draft", False)),
            prerelease=bool(data.get("prerelease", False)),
            target_commitish=data.get("target_commitish"),
        )

    def _rest_update(self, owner: str, repo: str, release_id: int, body: str, *, name: Optional[str] = None) -> ReleaseInfo:
        from utils.github_fallback import GithubFallback
        gh = GithubFallback()
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}"
        payload: Dict[str, Any] = {"body": body}
        if name is not None:
            payload["name"] = name
        data = self._request(gh, "PATCH", url, payload)
        return ReleaseInfo(
            id=int(data.get("id", release_id)),
            tag_name=data.get("tag_name", ""),
            html_url=data.get("html_url", ""),
            draft=bool(data.get("draft", False)),
            prerelease=bool(data.get("prerelease", False)),
            target_commitish=data.get("target_commitish"),
        )

    # -------- HTTP helpers --------
    def _request(self, gh, method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        import requests
        headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json"}
        attempt = 0
        max_attempts = 1 + Config.COMMENT_RETRY_MAX  # reuse retry policy
        while attempt < max_attempts:
            try:
                if method == "GET":
                    r = gh.session.get(url, headers=headers, timeout=self.timeout_s)
                elif method == "POST":
                    r = gh.session.post(url, headers=headers, data=json.dumps(payload or {}), timeout=self.timeout_s)
                elif method == "PATCH":
                    r = gh.session.patch(url, headers=headers, data=json.dumps(payload or {}), timeout=self.timeout_s)
                else:
                    raise ReleasePublishError(f"Unsupported method: {method}")
                sc = r.status_code
                if sc == 401 or sc == 403:
                    raise ReleasePublishError("Unauthorized", code="UNAUTHORIZED")
                if sc == 404:
                    if method == "GET":
                        return None
                    raise ReleasePublishError("Not found", code="NOT_FOUND")
                if sc == 429:
                    raise ReleasePublishError("Rate limited", code="RATE_LIMIT")
                if sc >= 500:
                    raise ReleasePublishError("Server error", code="NETWORK")
                if sc >= 400:
                    raise ReleasePublishError(f"HTTP {sc}")
                return r.json()
            except ReleasePublishError as e:
                if e.code in {"RATE_LIMIT", "NETWORK", "TIMEOUT"} and attempt + 1 < max_attempts:
                    time.sleep(0.5 * (2 ** attempt))
                    attempt += 1
                    continue
                raise
            except requests.Timeout:
                if attempt + 1 < max_attempts:
                    time.sleep(0.5 * (2 ** attempt))
                    attempt += 1
                    continue
                raise ReleasePublishError("Timeout", code="TIMEOUT")
            except requests.RequestException as e:
                if attempt + 1 < max_attempts:
                    time.sleep(0.5 * (2 ** attempt))
                    attempt += 1
                    continue
                raise ReleasePublishError(str(e), code="NETWORK")


