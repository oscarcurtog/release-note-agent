#!/usr/bin/env python3
"""Pydantic models for diff data structures."""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field

ChangeType = Literal["code", "docs", "tests", "config", "data", "other"]


class DiffFile(BaseModel):
    filename: str
    status: Literal[
        "added",
        "modified",
        "removed",
        "renamed",
        "copied",
        "changed",
        "unchanged",
        "other",
    ] = "modified"
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    previous_filename: Optional[str] = None
    is_binary: bool = False
    change_type: ChangeType = "other"
    patch: Optional[str] = None
    hunk_count: Optional[int] = None
    summary: Optional[str] = None

    model_config = {"extra": "ignore"}


class DiffBundle(BaseModel):
    pr_number: int
    base_sha: str
    head_sha: str
    total_files: int
    total_additions: int
    total_deletions: int
    total_changes: int
    truncated: bool = False
    files: List[DiffFile] = Field(default_factory=list)
    diagnostics: List[str] = Field(default_factory=list)


