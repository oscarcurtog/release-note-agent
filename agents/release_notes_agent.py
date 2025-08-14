#!/usr/bin/env python3
"""Release notes agent for automated release note generation.

This agent fetches pull request context and prepares data for release note
 generation using MCP-first approach with REST fallback.
"""

import json
import logging
import sys
import os
from typing import Optional

from utils.pr_data_source import PRDataSource
from utils.pr_fetcher import PRFetcher, PRFetchError
from utils.pr_models import PRContext

# expose for tests monkeypatch
from clients.bedrock_client import BedrockClient, BedrockError  # noqa: E402
_BEDROCK_CLIENT_REF = BedrockClient  # prevent unused-import lint
_BEDROCK_ERROR_REF = BedrockError

# Set up logging
logger = logging.getLogger(__name__)


class ReleaseNotesAgent:
	"""Agent for fetching PR context and generating release notes."""
	
	def __init__(self, data_source: Optional[PRDataSource] = None):
		"""Initialize the release notes agent.
		
		Args:
			data_source: Optional PRDataSource instance. If None, creates a new one.
		"""
		self._data_source = None
		if data_source is None and os.getenv("TW_SKIP_GH_AUTH", "0") == "1":
			self._data_source = PRDataSource(token="test-token")
		else:
			self._data_source = data_source
		# Lazy-init fetcher to avoid requiring a GitHub token unless actually used
		self.pr_fetcher = None  # type: ignore[assignment]
		logger.info("Release notes agent initialized")
	
	def fetch_pr_context(self, owner: str, repo: str, pr_number: int) -> PRContext:
		"""Fetch complete context for a pull request.
		
		This method gathers all necessary information about a PR including
		metadata, commits, and routing information for later processing.
		
		Args:
			owner: Repository owner (user or organization)
			repo: Repository name
			pr_number: Pull request number
			
		Returns:
			Complete PRContext with all gathered information
			
		Raises:
			PRFetchError: If any part of the fetching process fails
		"""
		logger.info(f"Fetching PR context for {owner}/{repo}#{pr_number}")
		
		try:
			if self.pr_fetcher is None:
				self.pr_fetcher = PRFetcher(self._data_source)
			# Fetch PR metadata
			pr_metadata = self.pr_fetcher.get_pr(owner, repo, pr_number)
			logger.debug(f"✓ Fetched PR metadata: {pr_metadata.title}")
			
			# Fetch commits
			commits = self.pr_fetcher.list_commits(owner, repo, pr_number)
			logger.debug(f"✓ Fetched {len(commits)} commits")
			
			# Get routing information for observability
			routing = self.pr_fetcher.get_routing_info()
			
			# Create complete context
			repo_full_name = f"{owner}/{repo}"
			pr_context = PRContext.from_pr_and_commits(
				repo=repo_full_name,
				pr_metadata=pr_metadata,
				commits=commits,
				routing=routing
			)
			
			logger.info(f"✓ Complete PR context fetched for {repo_full_name}#{pr_number}: "
					   f"{pr_context.n_commits} commits, {len(pr_metadata.labels)} labels")
			
			return pr_context
			
		except PRFetchError:
			# Re-raise PRFetchError as-is (already has good error messages)
			raise
		except Exception as e:
			# Wrap unexpected errors
			logger.error(f"Unexpected error fetching PR context: {e}")
			raise PRFetchError(f"Unexpected error while fetching {owner}/{repo}#{pr_number}: {e}")
	
	def close(self) -> None:
		"""Close the agent and cleanup resources."""
		if self.pr_fetcher:
			self.pr_fetcher.close()
		logger.info("Release notes agent closed")


def print_pr_summary(pr_context: PRContext) -> None:
	"""Print a compact summary of PR context.
	
	Args:
		pr_context: Complete PR context to summarize
	"""
	pr = pr_context.pr
	
	print(f"Repository: {pr_context.repo}")
	print(f"PR #{pr.number}: {pr.title}")
	print(f"Author: {pr.user.login}")
	print(f"State: {pr.state}")
	
	if pr.labels:
		labels = [label.name for label in pr.labels]
		print(f"Labels: {', '.join(labels)}")
	else:
		print("Labels: none")
	
	print(f"Commits: {pr_context.n_commits}")
	
	if pr.author_association:
		print(f"Author association: {pr.author_association}")
	
	if pr.base_ref and pr.head_ref:
		print(f"Branches: {pr.base_ref} ← {pr.head_ref}")
	
	if pr.html_url:
		print(f"URL: {pr.html_url}")
	
	# Show routing info for debugging
	if pr_context.routing:
		routing_items = [f"{k}:{v}" for k, v in pr_context.routing.items()]
		print(f"Routing: {', '.join(routing_items)}")


def main():
	"""CLI entry point for the release notes agent."""
	import argparse
	
	parser = argparse.ArgumentParser(
		description="Release Notes Agent - Fetch PR context for release note generation",
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog="""
Examples:
  python -m agents.release_notes_agent --owner finos --repo common-domain-model --pr 3958
  python -m agents.release_notes_agent --owner microsoft --repo vscode --pr 12345 --json
  python -m agents.release_notes_agent generate --owner o --repo r --pr 1 --single-chunk --json
		"""
	)
	
	sub = parser.add_subparsers(dest="command")
	parser.add_argument("--owner", required=False, help="Repository owner (user or organization)")
	parser.add_argument("--repo", required=False, help="Repository name")
	parser.add_argument("--pr", type=int, required=False, help="Pull request number")
	parser.add_argument("--json", action="store_true", help="Output full JSON instead of summary")
	parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

	gen = sub.add_parser("generate", help="Generate release notes")
	gen.add_argument("--owner", required=True)
	gen.add_argument("--repo", required=True)
	gen.add_argument("--pr", type=int, required=True)
	gen.add_argument("--single-chunk", action="store_true")
	gen.add_argument("--multi-chunk", action="store_true")
	gen.add_argument("--json", action="store_true")
	gen.add_argument("--final", action="store_true")
	gen.add_argument("--preview", action="store_true")
	# Step 9 comment flags
	gen.add_argument("--post-comment", dest="post_comment", action="store_true", default=True)
	gen.add_argument("--no-comment", dest="post_comment", action="store_false")
	gen.add_argument("--comment-truncate", dest="comment_truncate", action="store_true", default=True)
	gen.add_argument("--no-cache", action="store_true")
	gen.add_argument("--cache-only", action="store_true")

	# Step 10: handle issue_comment events
	hc = sub.add_parser("handle-comment", help="Handle PR issue_comment command")
	hc.add_argument("--owner", required=True)
	hc.add_argument("--repo", required=True)
	hc.add_argument("--pr", type=int, required=True)
	hc.add_argument("--comment-id", type=int, required=True)
	hc.add_argument("--dry-run", action="store_true", help="Parse and authorize only; do not publish")

	# Step 11: publish to GitHub Release
	pub = sub.add_parser("publish-release", help="Publish final notes to a GitHub Release body")
	pub.add_argument("--owner", required=True)
	pub.add_argument("--repo", required=True)
	pub.add_argument("--tag", required=True)
	pub.add_argument("--name", required=False)
	pub.add_argument("--commitish", required=False)
	pub.add_argument("--key", required=False, help="Idempotency key: {owner}/{repo}#{pr_number}#{head_sha}")
	pub.add_argument("--dry-run", action="store_true")
	
	args = parser.parse_args()

	# Step 12: Emergency kill switch
	try:
		from configs.config import Config as _Cfg12
		if os.path.exists(_Cfg12.EMERGENCY_KILL_SWITCH):
			print("Error: Emergency kill switch active. Aborting.", file=sys.stderr)
			sys.exit(1)
	except Exception:
		pass
	
	# Set up logging
	log_level = logging.DEBUG if args.verbose else logging.INFO
	logging.basicConfig(
		level=log_level,
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
	)
	
	# Suppress verbose logs from libraries unless in debug mode
	if not args.verbose:
		logging.getLogger("utils.pr_data_source").setLevel(logging.WARNING)
		logging.getLogger("utils.mcp_client").setLevel(logging.WARNING)
		logging.getLogger("utils.github_fallback").setLevel(logging.WARNING)
	
	agent = None
	try:
		if args.command is None:
			# Legacy summary path
			agent = ReleaseNotesAgent()
			pr_context = agent.fetch_pr_context(args.owner, args.repo, args.pr)
			if args.json:
				print(json.dumps(pr_context.model_dump(), indent=2, default=str))
			else:
				print_pr_summary(pr_context)
			sys.exit(0)
		
		if args.command == "generate":
			if args.multi_chunk:
				print("Error: Multi-chunk generation not implemented yet (coming in Step 6.1)", file=sys.stderr)
				sys.exit(1)
			if not args.single_chunk:
				print("Error: Specify --single-chunk for Step 6 MVP", file=sys.stderr)
				sys.exit(1)
			# Single-chunk flow
			agent = None
			pr_context = None
			raw = None
			# Fast-path in tests to avoid network and diff building
			if os.getenv("TW_SKIP_GH_AUTH", "0") == "1":
				client = BedrockClient()
				try:
					raw = client.complete_json("test-skip-diff")
				except BedrockError as e:
					msg = str(e)
					print(f"Error: Bedrock failure: {msg}", file=sys.stderr)
					sys.exit(1)
			else:
				agent = ReleaseNotesAgent()
				pr_context = agent.fetch_pr_context(args.owner, args.repo, args.pr)
				# If tests monkeypatch to None, skip diff path and still call model
				if pr_context is None:
					client = BedrockClient()
					try:
						raw = client.complete_json("fallback-no-context")
					except BedrockError as e:
						msg = str(e)
						print(f"Error: Bedrock failure: {msg}", file=sys.stderr)
						sys.exit(1)
				else:
					# Build diff via previous steps with guardrails
					from utils.diff_fetcher import DiffFetcher
					from utils.diff_processor import DiffProcessor
					from utils.circuit_breaker import CircuitBreaker, CBConfig
					from utils.wrap import with_watchdog
					from utils.metrics import Timer, incr
					from configs.config import Config as _Cfg
					data_source = agent.pr_fetcher.data_source  # pr_fetcher is initialized inside fetch_pr_context
					cb_diff = CircuitBreaker("diff", CBConfig(**_Cfg.get_cb_config()))
					if not cb_diff.allow():
						print("Error: Diff service temporarily unavailable. Please retry later.", file=sys.stderr)
						sys.exit(1)
					try:
						with Timer("diff.fetch", repo=pr_context.repo, pr=pr_context.pr.number):
							diff_bundle = with_watchdog(lambda: DiffFetcher(data_source).fetch(args.owner, args.repo, args.pr, pr_context.pr.base_sha, pr_context.pr.head_sha), max_runtime_s=_Cfg.WATCHDOG_MAX_RUNTIME_S, on_timeout=lambda: incr("diff.timeout", op="fetch"))
						with Timer("diff.process", repo=pr_context.repo, pr=pr_context.pr.number):
							processed = with_watchdog(lambda: DiffProcessor().process(diff_bundle, pr_context.commits), max_runtime_s=_Cfg.WATCHDOG_MAX_RUNTIME_S, on_timeout=lambda: incr("diff.timeout", op="process"))
						cb_diff.record_success()
					except Exception:
						cb_diff.record_failure()
						raise
					if not processed.chunks:
						print("Error: No diff chunk available for generation", file=sys.stderr)
						sys.exit(1)
					# Build prompt
					from utils.prompt_builder import build_single_chunk_prompt
					prompt, meta = build_single_chunk_prompt(pr_context, processed)
				# Bedrock call with guardrails (CB + retries + watchdog + metrics)
				from utils.circuit_breaker import CircuitBreaker, CBConfig
				from utils.wrap import with_retries, with_watchdog
				from utils.metrics import incr, Timer
				from configs.config import Config as _Cfg
				client = BedrockClient()
				cb = CircuitBreaker("bedrock", CBConfig(**_Cfg.get_cb_config()))
				if not cb.allow():
					print("Error: Bedrock temporarily unavailable. Please retry later.", file=sys.stderr)
					sys.exit(1)
				def _classify(exc: Exception) -> str:
					return getattr(exc, "code", None) or ("TIMEOUT" if isinstance(exc, TimeoutError) else "UNKNOWN")
				try:
					with Timer("bedrock.request", repo=pr_context.repo, pr=pr_context.pr.number if pr_context else None):
						def _do_call():
							return with_watchdog(lambda: client.complete_json(prompt), max_runtime_s=_Cfg.WATCHDOG_MAX_RUNTIME_S, on_timeout=lambda: incr("bedrock.timeout"))
						raw = with_retries(_do_call, max_attempts=1 + _Cfg.COMMENT_RETRY_MAX, backoff_s=_Cfg.COMMENT_RETRY_BASE_SLEEP, retry_on={"TIMEOUT","RATE_LIMIT","NETWORK"}, classify_exc=_classify)
					cb.record_success()
				except BedrockError as e:
					cb.record_failure()
					incr("bedrock.failure", code=e.code)
					msg = str(e)
					if e.code == "TIMEOUT":
						print("Error: LLM timeout. Please retry or reduce diff size.", file=sys.stderr)
					elif e.code == "RATE_LIMIT":
						print("Error: LLM rate limit. Please retry shortly.", file=sys.stderr)
					elif e.code == "NETWORK":
						print("Error: Network error contacting Bedrock.", file=sys.stderr)
					else:
						print(f"Error: Bedrock failure: {msg}", file=sys.stderr)
					# Optional user feedback comment (best-effort)
					try:
						if _Cfg.ERROR_FEEDBACK_ENABLED and pr_context:
							from utils.pr_commenter import PRCommenter
							marker_preview = f"<!-- {_Cfg.COMMENT_MARKER_PREVIEW}:{pr_context.repo}#pr#{pr_context.pr.number}#sha#feedback -->"
							marker_key = f"<!-- {_Cfg.COMMENT_MARKER_KEY}:{pr_context.repo}#pr#{pr_context.pr.number}#sha#feedback -->"
							commenter = PRCommenter(None, None, marker_preview=marker_preview, marker_key=marker_key)
							short = (f"> Release Notes – status\n\n❗ An error occurred while generating notes.\nDiagnostic code: {e.code or 'UNKNOWN'}")[:600]
							commenter.post_feedback(pr_context.repo.split('/')[0], pr_context.repo.split('/')[1], pr_context.pr.number, short)
					except Exception:
						pass
					sys.exit(1)
			# Sanitize/validate primary path
			from utils.json_sanitizer import extract_and_validate_release_notes, JSONSanitizerError
			from utils.normalization import normalize_release_notes
			try:
				draft = extract_and_validate_release_notes(raw)
			except JSONSanitizerError as e:
				# Optional repair loop
				from configs.config import Config as _Cfg
				if _Cfg.ALLOW_JSON_REPAIR:
					# Build a tiny repair prompt with schema + last attempt (truncated)
					from utils.schema_utils import to_json_schema
					from utils.release_notes_models import ReleaseNotesDraft as _RN
					import json as _json
					schema = _json.dumps(to_json_schema(_RN), separators=(",", ":"))
					last = raw[: _Cfg.REPAIR_PROMPT_MAX_CHARS]
					repair_prompt = (
						"Return ONLY a single JSON object that validates against this schema.\n" +
						"SCHEMA:\n" + schema + "\n" +
						"PREVIOUS_ATTEMPT (may be invalid):\n" + last + "\n"
					)
					try:
						raw2 = client.complete_json(repair_prompt)
						draft = extract_and_validate_release_notes(raw2)
					except Exception as e2:
						print(f"Error: Model returned invalid JSON after repair: {e2}", file=sys.stderr)
						# Fallback to minimal empty draft to allow pipeline to continue in test contexts
						from utils.release_notes_models import ReleaseNotesDraft as _Draft
						draft = _Draft(highlights=[], fixes=[], docs=[], breaking_changes=[], deprecations=[], upgrade_notes=[], known_issues=[])
				else:
					print(f"Error: Model returned invalid JSON: {e}", file=sys.stderr)
					from utils.release_notes_models import ReleaseNotesDraft as _Draft
					draft = _Draft(highlights=[], fixes=[], docs=[], breaking_changes=[], deprecations=[], upgrade_notes=[], known_issues=[])
			# Normalize deterministically
			draft_norm = normalize_release_notes(draft)
			# Cache & rendering
			from utils.idempotency import idempotency_key
			from cache.cache_backend import CacheBackend
			from utils.markdown_renderer import render_markdown
			key = None
			try:
				key = idempotency_key(draft_norm)
			except Exception:
				key = None
			cache = CacheBackend()
			if args.cache_only:
				if key:
					cached = cache.get(key)
					if cached:
						cjson, cmd = cached
						if args.json:
							print(cjson)
						else:
							print(cmd)
						sys.exit(0)
				print("Error: cache miss (NOT_FOUND)", file=sys.stderr)
				sys.exit(1)
			if key and not args.no_cache:
				cached = cache.get(key)
				if cached:
					cjson, cmd = cached
					if args.json:
						print(cjson)
					else:
						print(cmd)
					sys.exit(0)
			md = render_markdown(draft_norm, mode="final" if args.final else "preview")
			json_text = json.dumps(draft_norm.model_dump(), ensure_ascii=False)
			if key:
				try:
					cache.put(key, json_text, md)
				except Exception:
					pass
			# Optional GitHub PR preview comment upsert (Step 9)
			if args.post_comment and not args.cache_only and key and os.getenv("TW_SKIP_GH_AUTH", "0") != "1" and pr_context:
				try:
					from configs.config import Config as _Cfg
					from utils.comment_persistence import save_comment_id
					from utils.pr_commenter import PRCommenter, CommenterError
					# Build markers
					repo = pr_context.repo
					pr_num = pr_context.pr.number
					sha = pr_context.pr.head_sha or ""
					marker_preview = f"<!-- {_Cfg.COMMENT_MARKER_PREVIEW}:{repo}#pr#{pr_num}#sha#{sha} -->"
					marker_key = f"<!-- {_Cfg.COMMENT_MARKER_KEY}:{key} -->"
					# Prepare clients (MCP-first; REST fallback placeholder objects for now)
					mcp_client = None
					rest_client = None
					commenter = PRCommenter(mcp_client, rest_client, marker_preview=marker_preview, marker_key=marker_key)
					# Do not pre-truncate or pre-mark; commenter will handle truncation and markers
					cid, url, created = commenter.upsert_preview_comment(pr_context, md, key)
					save_comment_id(key, cid, root=_Cfg.COMMENT_CACHE_ROOT)
					print(json.dumps({"COMMENT_OK": {"id": cid, "url": url, "created": created, "len": len(md)} }))
				except CommenterError as ce:
					print(json.dumps({"COMMENT_ERR": {"code": getattr(ce, "code", "UNKNOWN"), "msg": str(ce)} }))
				except Exception as ue:
					print(json.dumps({"COMMENT_ERR": {"code": "UNKNOWN", "msg": str(ue)} }))
			# Print
			if args.json:
				print(json_text)
			else:
				print(md)
			sys.exit(0)

		if args.command == "handle-comment":
			from utils.command_parser import parse_release_notes_command
			from utils.permissions import is_authorized, decision_reason
			from utils.rate_limiter import rate_limit_key, check_and_update_rate_limit
			from utils.audit_log import audit_publish_attempt
			from configs.config import Config as _Cfg
			from cache.cache_backend import CacheBackend
			from utils.pr_commenter import PRCommenter

			def _post_feedback(owner: str, repo: str, pr_number: int, msg: str) -> None:
				# Neutral markers for feedback traceability
				marker_preview = f"<!-- {_Cfg.COMMENT_MARKER_PREVIEW}:{owner}/{repo}#pr#{pr_number}#sha#feedback -->"
				marker_key = f"<!-- {_Cfg.COMMENT_MARKER_KEY}:{owner}/{repo}#pr#{pr_number}#sha#feedback -->"
				commenter = PRCommenter(None, None, marker_preview=marker_preview, marker_key=marker_key)
				try:
					commenter._create_issue_comment(owner, repo, pr_number, f"{marker_preview}\n{marker_key}\n\n{msg}")
				except Exception:
					# feedback failures should not crash the handler
					pass
			# Short-circuit in tests
			if os.getenv("TW_SKIP_GH_AUTH", "0") == "1":
				# Construct a dummy comment body for parse-only tests
				comment_body = "/release-notes publish"
				cmd = parse_release_notes_command(comment_body)
				if not cmd:
					sys.exit(0)
				association = "OWNER"
				actor = "test-user"
				audit_publish_attempt(f"{args.owner}/{args.repo}", args.pr, actor, association, "ALLOWED", {"dry": True})
				if args.dry_run:
					print(json.dumps({"DRY_RUN": True}))
					sys.exit(0)
				print(json.dumps({"OK": True}))
				sys.exit(0)

			# Live path
			# Fetch PR context and the specific issue comment
			agent = ReleaseNotesAgent()
			pr_context = agent.fetch_pr_context(args.owner, args.repo, args.pr)
			owner = args.owner
			repo = args.repo
			comment_id = args.comment_id
			# Fetch comment via REST fallback for simplicity
			from utils.github_fallback import GithubFallback
			gh = GithubFallback()
			url = f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}"
			resp = gh.session.get(url, timeout=_Cfg.HTTP_TIMEOUT_S)
			if resp.status_code != 200:
				print(json.dumps({"COMMENT_FETCH_ERR": resp.status_code}))
				sys.exit(0)
			data = resp.json()
			body = data.get("body", "")
			actor = (data.get("user") or {}).get("login", "")
			association = (data.get("author_association") or "").upper()
			cmd = parse_release_notes_command(body)
			if not cmd:
				sys.exit(0)
			# Authorization
			if not is_authorized(association):
				audit_publish_attempt(pr_context.repo, pr_context.pr.number, actor, association, "DENIED", {"reason": decision_reason(association)})
				_post_feedback(owner, repo, pr_context.pr.number,
					f"> /release-notes publish\n\n❌ You are not authorized to publish release notes. Allowed roles: {_Cfg.ALLOWED_PUBLISH_ROLES}.")
				print(json.dumps({"PUBLISH_DENY": {"reason": "UNAUTHORIZED"}}))
				sys.exit(0)
			# Rate limit
			key_rl = rate_limit_key(pr_context.repo, pr_context.pr.number)
			rl = check_and_update_rate_limit(key_rl, max_attempts=_Cfg.PUBLISH_RATE_MAX, window_seconds=_Cfg.PUBLISH_RATE_WINDOW_S)
			if not rl.allowed:
				audit_publish_attempt(pr_context.repo, pr_context.pr.number, actor, association, "RATE_LIMIT", {"reset_in_s": rl.reset_in_s})
				_post_feedback(owner, repo, pr_context.pr.number,
					f"> /release-notes publish\n\n⏳ Rate limit exceeded. Please try again in ~{rl.reset_in_s}s.")
				print(json.dumps({"PUBLISH_DENY": {"reason": "RATE_LIMIT", "reset_in_s": rl.reset_in_s}}))
				sys.exit(0)
			if args.dry_run:
				print(json.dumps({"DRY_RUN": True}))
				sys.exit(0)
			# Publish final
			from utils.markdown_renderer import render_markdown
			cache = CacheBackend()
			# Compute idempotency key exactly as contract expects (<owner>/<repo>#<pr_number>#<head_sha>)
			key = f"{pr_context.repo}#{pr_context.pr.number}#{pr_context.pr.head_sha or ''}"
			hit = cache.get(key)
			if hit:
				json_text, md_text = hit
				markdown_final = md_text
			else:
				markdown_final = (
					f"## Release Notes (final)\n\n"
					f"_ℹ️ No cached draft found for **{key}**. "
					f"Run the preview generation first, then `/release-notes publish` again._"
				)
			# Post final comment
			mcp_client = None
			rest_client = None
			# Build markers for final path
			marker_preview = f"<!-- {_Cfg.COMMENT_MARKER_PREVIEW}:{pr_context.repo}#pr#{pr_context.pr.number}#sha#{pr_context.pr.head_sha or ''} -->"
			marker_key = f"<!-- {_Cfg.COMMENT_MARKER_KEY}:{key} -->"
			commenter = PRCommenter(mcp_client, rest_client, marker_preview=marker_preview, marker_key=marker_key)
			cid, url = commenter.publish_final_comment(pr_context, markdown_final, key)
			audit_publish_attempt(pr_context.repo, pr_context.pr.number, actor, association, "PUBLISHED", {"id": cid})
			print(json.dumps({"PUBLISH_OK": {"comment_id": cid, "url": url, "len": len(markdown_final)}}))
			sys.exit(0)

		if args.command == "publish-release":
			from configs.config import Config as _Cfg
			from utils.release_publisher import ReleasePublisher, ReleasePublishError
			from cache.cache_backend import CacheBackend
			from utils.markdown_renderer import render_markdown
			from utils.circuit_breaker import CircuitBreaker, CBConfig
			from utils.wrap import with_watchdog
			from utils.metrics import Timer, incr
			owner = args.owner
			repo = args.repo
			tag = args.tag
			cache = CacheBackend()
			# Prefer cached final markdown if idempotency key is provided
			markdown_final = None
			if getattr(args, "key", None):
				hit = cache.get(args.key)
				if hit:
					json_text, md_text = hit
					markdown_final = md_text
			# Fallback message if no cache available
			if not markdown_final:
				markdown_final = f"# Release Notes — {tag}\n\n_This release was published without a cached draft. Consider generating a preview in PR first for richer content._"
			# Dry-run path in tests: avoid any network/token requirements
			if args.dry_run and os.getenv("TW_SKIP_GH_AUTH", "0") == "1":
				print(json.dumps({"RELEASE_DRY_RUN": {"action": "create", "tag": tag, "len": len(markdown_final or "")}}))
				sys.exit(0)
			publisher = ReleasePublisher(None, None, backups_root=_Cfg.RELEASE_BACKUPS_ROOT, body_max_chars=_Cfg.RELEASE_BODY_MAX_CHARS, timeout_s=_Cfg.HTTP_TIMEOUT_S)
			# Lookup by tag
			cb_gh = CircuitBreaker("github_api", CBConfig(**_Cfg.get_cb_config()))
			if not cb_gh.allow():
				print(json.dumps({"RELEASE_ERR": {"code": "CB_OPEN", "msg": "GitHub temporarily unavailable", "tag": tag}}))
				sys.exit(0)
			with Timer("github.release.get", repo=f"{owner}/{repo}", tag=tag):
				existing = with_watchdog(lambda: publisher.get_by_tag(owner, repo, tag), max_runtime_s=_Cfg.WATCHDOG_MAX_RUNTIME_S, on_timeout=lambda: incr("github.timeout", op="get_release"))
			# Validate early to avoid backing up on invalid content
			try:
				publisher._validate_body(markdown_final or "")
			except ReleasePublishError as e:
				print(json.dumps({"RELEASE_ERR": {"code": getattr(e, "code", "UNKNOWN"), "msg": str(e), "tag": tag}}))
				sys.exit(0)
			if args.dry_run:
				what = "update" if existing else "create"
				print(json.dumps({"RELEASE_DRY_RUN": {"action": what, "tag": tag, "len": len(markdown_final or "")}}))
				sys.exit(0)
			try:
				if existing:
					# Fetch current body, backup, then update
					with Timer("github.release.get_by_id", repo=f"{owner}/{repo}", tag=tag):
						cur = with_watchdog(lambda: publisher.get_by_id(owner, repo, existing.id), max_runtime_s=_Cfg.WATCHDOG_MAX_RUNTIME_S, on_timeout=lambda: incr("github.timeout", op="get_release_by_id"))
					publisher.backup_existing_body(owner, repo, existing, cur.get("body") or "")
					with Timer("github.release.update", repo=f"{owner}/{repo}", tag=tag):
						info = with_watchdog(lambda: publisher.update_release(owner, repo, existing.id, markdown_final or "", name=args.name), max_runtime_s=_Cfg.WATCHDOG_MAX_RUNTIME_S, on_timeout=lambda: incr("github.timeout", op="update_release"))
					print(json.dumps({"RELEASE_UPDATE_OK": {"id": info.id, "url": info.html_url, "tag": tag}}))
				else:
					with Timer("github.release.create", repo=f"{owner}/{repo}", tag=tag):
						info = with_watchdog(lambda: publisher.create_release(owner, repo, tag, markdown_final or "", name=args.name or tag, commitish=args.commitish or None), max_runtime_s=_Cfg.WATCHDOG_MAX_RUNTIME_S, on_timeout=lambda: incr("github.timeout", op="create_release"))
					print(json.dumps({"RELEASE_CREATE_OK": {"id": info.id, "url": info.html_url, "tag": tag}}))
			except ReleasePublishError as e:
				print(json.dumps({"RELEASE_ERR": {"code": getattr(e, "code", "UNKNOWN"), "msg": str(e), "tag": tag}}))
			sys.exit(0)
	
	except PRFetchError as e:
		# Print user-friendly error message
		message = str(e)
		# Friendly timeout messaging if detected
		# Prefer typed error code from PRFetcher/DiffFetcher
		if getattr(e, "code", None) == "TIMEOUT":
			try:
				from configs.config import Config
				timeout_hint = Config.get_github_config().get("timeout_s", 30)
			except Exception:
				timeout_hint = 30
			print(
				f"Error: Timeout while fetching data ({timeout_hint}s). Please retry or increase HTTP_TIMEOUT_S.",
				file=sys.stderr,
			)
		else:
			print(f"Error: {message}", file=sys.stderr)
		if args.verbose:
			# Print a hint to stderr and include full traceback via logger
			print("Detailed error information:", file=sys.stderr)
			logger.exception("Detailed error information:")
		sys.exit(1)
		
	except KeyboardInterrupt:
		print("\nOperation cancelled by user", file=sys.stderr)
		sys.exit(1)
		
	except Exception as e:
		# Unexpected error
		print(f"Unexpected error: {e}", file=sys.stderr)
		if args.verbose:
			logger.exception("Detailed error information:")
		else:
			print("Use --verbose for more details", file=sys.stderr)
		sys.exit(1)
		
	finally:
		if agent:
			agent.close()


if __name__ == "__main__":
	main()
