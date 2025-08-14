#!/usr/bin/env python3
"""Release notes models (MVP) for structured output.

These models define the contract that Step 6 (prompting) will target.
"""
from typing import Literal, Optional, List
from pydantic import BaseModel, Field, confloat, constr, ConfigDict

SCHEMA_VERSION = "v1"

ChangeType = Literal[
	"feature",
	"fix",
	"docs",
	"perf",
	"refactor",
	"test",
	"chore",
	"build",
	"ci",
	"style",
	"revert",
	"security",
]

ScopeType = Literal[
	"api",
	"ui",
	"core",
	"infra",
	"build",
	"data",
	"docs",
	"tests",
	"config",
	"deps",
	"release",
]

VersionIncrement = Literal["major", "minor", "patch", "none"]


class _StrictModel(BaseModel):
	model_config = ConfigDict(extra="forbid")


class ReleaseNoteItem(_StrictModel):
	"""One change item to appear in release notes under various sections."""

	type: ChangeType
	title: constr(min_length=3, max_length=200)
	details: Optional[constr(max_length=2000)] = None
	scope: Optional[ScopeType] = None
	breaking: bool = False
	confidence: Optional[confloat(ge=0.0, le=1.0)] = None
	issue_refs: Optional[List[constr(strip_whitespace=True, min_length=1, max_length=50)]] = None
	components: Optional[List[constr(strip_whitespace=True, min_length=1, max_length=50)]] = None
	files: Optional[List[str]] = None
	commit_shas: Optional[List[constr(min_length=7, max_length=40)]] = None

    


class DeprecationItem(_StrictModel):
	"""A deprecation note with optional effective version."""

	title: constr(min_length=3, max_length=200)
	details: Optional[constr(max_length=2000)] = None
	effective_version: Optional[constr(min_length=1, max_length=50)] = None

    


class ReleaseNotesDraft(_StrictModel):
	"""Structured draft of release notes, to be refined or published later."""

	schema_version: constr(min_length=1, max_length=20) = Field(default=SCHEMA_VERSION)
	version_increment: VersionIncrement = "none"
	highlights: List[ReleaseNoteItem] = Field(default_factory=list)
	fixes: List[ReleaseNoteItem] = Field(default_factory=list)
	docs: List[ReleaseNoteItem] = Field(default_factory=list)
	breaking_changes: List[ReleaseNoteItem] = Field(default_factory=list)
	deprecations: List[DeprecationItem] = Field(default_factory=list)
	upgrade_notes: List[constr(max_length=2000)] = Field(default_factory=list)
	technical_debt_notes: Optional[constr(max_length=2000)] = None
	known_issues: Optional[List[constr(max_length=500)]] = None
	confidence_overall: Optional[confloat(ge=0.0, le=1.0)] = None
	# optional meta for traceability
	repo: Optional[str] = None
	pr_number: Optional[int] = None
	head_sha: Optional[constr(min_length=7, max_length=40)] = None

    
