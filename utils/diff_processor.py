#!/usr/bin/env python3
"""Diff preprocessing and chunking for LLM-ready input.

Transforms DiffBundle → ProcessedDiff with trimmed patches, grouping, chunking,
token estimates, and deterministic degradation.
"""

from __future__ import annotations

import logging
import math
import re
from typing import List, Optional, Tuple
from enum import Enum

from pydantic import BaseModel, Field

from utils.diff_models import DiffBundle, DiffFile
from utils.pr_models import CommitInfo
from configs.config import Config

logger = logging.getLogger(__name__)


class ProcessedFile(BaseModel):
    path: str
    status: str
    previous_path: Optional[str] = None
    change_type: str
    is_binary: bool = False
    additions: int = 0
    deletions: int = 0
    hunk_count: int = 0
    summary: str = ""
    patch_trimmed: Optional[str] = None
    tokens_est: int = 0


class ProcessedChunk(BaseModel):
    idx: int
    files: List[ProcessedFile]
    files_count: int
    tokens_est: int
    diagnostics: List[str] = Field(default_factory=list)


class DegradationLevel(str, Enum):
    L1 = "full"
    L2 = "files_only"
    L3 = "commits_only"


class ProcessedDiff(BaseModel):
    chunks: List[ProcessedChunk]
    total_files: int
    total_tokens_est: int
    truncated: bool = False
    degradation: DegradationLevel = DegradationLevel.L1
    diagnostics: List[str] = Field(default_factory=list)
    degradation_reason: Optional[str] = None
    commits_summary: Optional[List["CommitSummary"]] = None
class CommitSummary(BaseModel):
    sha_short: str
    author_login: Optional[str] = None
    message_first_line: str




class DiffProcessor:
    def __init__(
        self,
        *,
        context_lines: int = 3,
        max_files_per_chunk: int = 15,
        max_chunks: int = 5,
        max_tokens_per_chunk: Optional[int] = None,
        token_chars_per_token: Optional[float] = None,
        group_by_dir_depth: int = 1,
    ) -> None:
        self.context_lines = context_lines
        self.max_files_per_chunk = max_files_per_chunk
        self.max_chunks = max_chunks
        # Pull defaults from Config if not provided
        budgets = Config.get_diff_budget_config()
        self.max_tokens_per_chunk = max_tokens_per_chunk if max_tokens_per_chunk is not None else int(budgets["hard_budget"]) 
        self.token_chars_per_token = token_chars_per_token if token_chars_per_token is not None else float(budgets["tokens_per_char"]) 
        soft_ratio = float(budgets.get("soft_ratio", 0.6))
        self.group_by_dir_depth = group_by_dir_depth
        # Reserve ~ (1 - soft_ratio) for synthesis later → soft_ratio for chunking
        self._soft_chunk_budget = int(self.max_tokens_per_chunk * soft_ratio)

    def process(self, bundle: DiffBundle, commits: List[CommitInfo]) -> ProcessedDiff:
        processed_files: List[ProcessedFile] = []

        for f in bundle.files:
            pf = self._to_processed_file(f)
            processed_files.append(pf)

        total_files = len(processed_files)

        # Group and order deterministically
        grouped = self._group_and_order(processed_files)

        # Chunk under soft budget and file count
        chunks = self._build_chunks(grouped)

        # If we exceeded limits, degrade to L2 then L3 as needed
        degradation = DegradationLevel.L1
        diagnostics: List[str] = []
        degradation_reason: Optional[str] = None
        # Determine which constraint triggers first
        over_chunks = len(chunks) > self.max_chunks
        over_budget = any(c.tokens_est > self.max_tokens_per_chunk for c in chunks)
        if over_chunks or over_budget:
            degradation = DegradationLevel.L2
            degradation_reason = "budget" if over_budget and not over_chunks else "chunks"
            diagnostics.append("degraded to files_only due to token budget/chunk limits")
            # Drop patches for all files and rebuild chunks
            for pf in processed_files:
                pf.patch_trimmed = None
                pf.tokens_est = self._estimate_tokens(pf.summary)
            grouped = self._group_and_order(processed_files)
            chunks = self._build_chunks(grouped)

        over_chunks = len(chunks) > self.max_chunks
        over_budget = any(c.tokens_est > self.max_tokens_per_chunk for c in chunks)
        if over_chunks or over_budget:
            degradation = DegradationLevel.L3
            if degradation_reason is None:
                degradation_reason = "chunks" if over_chunks else "budget"
            diagnostics.append("degraded to commits_only due to >max chunks after files_only")
            # Produce a single empty chunk; prompt will rely on commits later
            chunks = [ProcessedChunk(idx=0, files=[], files_count=0, tokens_est=0, diagnostics=["commits_only"])]

        total_tokens_est = sum(c.tokens_est for c in chunks)

        if bundle.truncated:
            diagnostics.append("input bundle truncated at fetch stage")
            if degradation_reason is None:
                degradation_reason = "input_truncated"

        # Commit summaries for L3
        commits_summary = None
        if degradation == DegradationLevel.L3:
            # Always include a list for L3 to keep JSON shape consistent
            commits_summary = [
                CommitSummary(
                    sha_short=c.sha[:8],
                    author_login=c.author_login,
                    message_first_line=(c.message or (c.raw_message.split("\n")[0] if c.raw_message else "")),
                )
                for c in commits[:20]
            ] if commits else []

        pdiff = ProcessedDiff(
            chunks=chunks,
            total_files=total_files,
            total_tokens_est=total_tokens_est,
            truncated=bundle.truncated,
            degradation=degradation,
            diagnostics=diagnostics,
            degradation_reason=degradation_reason,
            commits_summary=commits_summary,
        )

        logger.info(
            f"Processed diff: files={total_files}, chunks={len(chunks)}, degradation={degradation}"
        )
        return pdiff

    def _to_processed_file(self, f: DiffFile) -> ProcessedFile:
        # Trim patch to K context lines per hunk
        trimmed = self._trim_patch(f.patch) if (not f.is_binary and f.patch) else None
        hunk_count = self._count_hunks_from_patch(trimmed) if trimmed else (f.hunk_count or 0)
        # Deterministic summary
        summary = self._summarize_file(f, hunk_count)

        tokens_est = self._estimate_tokens(trimmed if trimmed else summary)

        return ProcessedFile(
            path=f.filename,
            status=f.status,
            previous_path=f.previous_filename,
            change_type=f.change_type,
            is_binary=f.is_binary,
            additions=f.additions,
            deletions=f.deletions,
            hunk_count=hunk_count,
            summary=summary,
            patch_trimmed=trimmed,
            tokens_est=tokens_est,
        )

    def _group_and_order(self, files: List[ProcessedFile]) -> List[ProcessedFile]:
        # Group by top-level directory and change_type bucket
        def top_dir(path: str) -> str:
            parts = path.split("/")
            depth = max(1, self.group_by_dir_depth)
            return "/".join(parts[:depth]) if parts else path

        # Order of change types
        type_order = {t: i for i, t in enumerate(["code", "config", "data", "docs", "tests"])}

        def key_fn(pf: ProcessedFile):
            binary_rank = 0 if pf.is_binary else 1  # binary first to satisfy deterministic expectations
            return (
                binary_rank,
                type_order.get(pf.change_type, 999),
                top_dir(pf.path),
                pf.path,
            )

        files_sorted = sorted(files, key=key_fn)
        return files_sorted

    def _build_chunks(self, files: List[ProcessedFile]) -> List[ProcessedChunk]:
        chunks: List[ProcessedChunk] = []
        current: List[ProcessedFile] = []
        tokens = 0

        def flush(idx: int):
            if not current:
                return
            chunks.append(
                ProcessedChunk(
                    idx=idx,
                    files=list(current),
                    files_count=len(current),
                    tokens_est=tokens,
                )
            )

        idx = 0
        for pf in files:
            pf_tokens = pf.tokens_est
            need_flush = (
                len(current) >= self.max_files_per_chunk or (tokens + pf_tokens) > self._soft_chunk_budget
            )
            if need_flush:
                flush(idx)
                idx += 1
                current = []
                tokens = 0

            current.append(pf)
            tokens += pf_tokens

        flush(idx)

        # Ensure hard cap not exceeded in any chunk; if so, add diagnostic per chunk
        for ch in chunks:
            if ch.tokens_est > self.max_tokens_per_chunk:
                ch.diagnostics.append("hard token cap exceeded")
        return chunks

    def _trim_patch(self, patch: str) -> Optional[str]:
        if not patch:
            return None
        lines = patch.splitlines()
        out: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("@@"):
                # Start of hunk
                out.append("@@")  # normalize header to single token for deterministic counting
                # Collect hunk block until next @@ or end
                j = i + 1
                block: List[str] = []
                while j < len(lines) and not lines[j].startswith("@@"):
                    block.append(lines[j])
                    j += 1
                # Trim block context
                trimmed_block = self._trim_hunk_block(block)
                out.extend(trimmed_block)
                i = j
                continue
            i += 1
        return "\n".join(out) if out else None

    def _trim_hunk_block(self, block: List[str]) -> List[str]:
        # Keep all change lines (+/- but not file headers), limit context ' ' lines to K around change runs
        change_idx = [idx for idx, l in enumerate(block) if (l.startswith("+") or l.startswith("-")) and not l.startswith("+++") and not l.startswith("---")]
        if not change_idx:
            # No changes? return up to first K lines as context
            return block[: self.context_lines]
        keep = set()
        K = self.context_lines
        # Identify runs of change indices
        runs: List[Tuple[int, int]] = []
        start = change_idx[0]
        prev = start
        for idx in change_idx[1:]:
            if idx == prev + 1:
                prev = idx
            else:
                runs.append((start, prev))
                start = idx
                prev = idx
        runs.append((start, prev))
        for a, b in runs:
            # include change lines
            for t in range(a, b + 1):
                keep.add(t)
            # include K context lines before and after this run
            for t in range(max(0, a - K), a):
                keep.add(t)
            for t in range(b + 1, min(len(block), b + 1 + K)):
                keep.add(t)
        # Emit in order, compressing nothing else
        out: List[str] = []
        last_kept = -10
        for idx, l in enumerate(block):
            if idx in keep:
                out.append(l)
                last_kept = idx
        return out

    def _count_hunks_from_patch(self, patch: Optional[str]) -> int:
        if not patch:
            return 0
        return len(re.findall(r"^@@", patch, flags=re.MULTILINE))

    def _summarize_file(self, f: DiffFile, hunk_count: int) -> str:
        parts = []
        # Mention rename if applicable
        if f.status == "renamed" and f.previous_filename:
            parts.append(f"renamed from {f.previous_filename} to {f.filename}.")
        else:
            parts.append(f"{f.status} {f.change_type}.")
        parts.append(f"{hunk_count} hunks (+{f.additions}/-{f.deletions}).")
        # Light keywords heuristics
        if f.patch and not f.is_binary:
            p = f.patch
            hints = []
            if re.search(r"\bclass\b|\binterface\b|\bpublic\b|\bdef\b", p):
                hints.append("classes/functions")
            if re.search(r"\bdeprecated\b|@Api|schema|import |version", p):
                hints.append("api/schema/imports")
            if hints:
                parts.append("Touches " + " and ".join(hints) + ".")
        return " ".join(parts)[:400]  # keep concise

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return math.ceil(len(text) / max(1, self.token_chars_per_token))


