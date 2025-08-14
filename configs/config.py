import os
from typing import Dict, Any

class Config:
	"""Configuration for the comparison agent."""
	
	# AWS Bedrock Configuration
	AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
	BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
	
	# LangSmith Configuration
	LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
	LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "technical-writer")
	LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
	
	# File paths
	FILES_DIR = "files"

	# Diff behavior
	TREAT_SVG_AS_TEXT = bool(int(os.getenv("TREAT_SVG_AS_TEXT", "1")))
	# Diff processor budgets
	DIFF_SOFT_BUDGET_RATIO = float(os.getenv("DIFF_SOFT_BUDGET_RATIO", "0.60"))
	DIFF_HARD_TOKEN_BUDGET = int(os.getenv("DIFF_HARD_TOKEN_BUDGET", "6000"))
	DIFF_TOKENS_PER_CHAR = float(os.getenv("DIFF_TOKENS_PER_CHAR", "4.0"))
	
	# GitHub MCP Configuration
	GITHUB_MCP_ENDPOINT = os.getenv("GITHUB_MCP_ENDPOINT", "https://api.githubcopilot.com/mcp/").rstrip('/')
	GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
	HTTP_TIMEOUT_S = int(os.getenv("HTTP_TIMEOUT_S", "30"))
	
	# Step 7 feature flags
	ALLOW_JSON_REPAIR = bool(int(os.getenv("ALLOW_JSON_REPAIR", "1")))
	ALLOW_PARTIAL_RESULTS = bool(int(os.getenv("ALLOW_PARTIAL_RESULTS", "0")))
	REPAIR_PROMPT_MAX_CHARS = int(os.getenv("REPAIR_PROMPT_MAX_CHARS", "4000"))
	EMPTY_SECTIONS_ERROR = bool(int(os.getenv("EMPTY_SECTIONS_ERROR", "0")))
	NORMALIZE_COLLAPSE_SPACES = bool(int(os.getenv("NORMALIZE_COLLAPSE_SPACES", "1")))
	NORMALIZE_SORT_CASEFOLD = bool(int(os.getenv("NORMALIZE_SORT_CASEFOLD", "1")))
	
	# Severity levels for gap analysis
	SEVERITY_LEVELS = {
		"CRITICAL": "Critical missing or divergent sections that affect core functionality",
		"HIGH": "Important missing or divergent sections that impact business logic",
		"MEDIUM": "Moderate missing or divergent sections that may affect operations",
		"LOW": "Minor missing or divergent sections with minimal impact"
	}
	
	# Cache config
	CACHE_ROOT = os.getenv("CACHE_ROOT", ".cache/release_notes")
	CACHE_ENABLED = bool(int(os.getenv("CACHE_ENABLED", "1")))
	CACHE_ATOMIC_WRITES = bool(int(os.getenv("CACHE_ATOMIC_WRITES", "1")))
	RENDER_EMPTY_PLACEHOLDER = bool(int(os.getenv("RENDER_EMPTY_PLACEHOLDER", "1")))

	# Step 9: PR comment management
	COMMENT_MARKER_PREVIEW = os.getenv("COMMENT_MARKER_PREVIEW", "RELEASE_NOTES_PREVIEW")
	COMMENT_MARKER_KEY = os.getenv("COMMENT_MARKER_KEY", "RELEASE_NOTES_KEY")
	MAX_GH_COMMENT_CHARS = int(os.getenv("MAX_GH_COMMENT_CHARS", "65000"))
	COMMENT_RETRY_MAX = int(os.getenv("COMMENT_RETRY_MAX", "2"))
	COMMENT_RETRY_BASE_SLEEP = float(os.getenv("COMMENT_RETRY_BASE_SLEEP", "0.5"))
	COMMENT_CACHE_ROOT = os.getenv("COMMENT_CACHE_ROOT", ".cache/release_notes/comments")

	# Step 10: manual publish
	ALLOWED_PUBLISH_ROLES = os.getenv("ALLOWED_PUBLISH_ROLES", "OWNER,MEMBER,COLLABORATOR")
	PUBLISH_RATE_MAX = int(os.getenv("PUBLISH_RATE_MAX", "3"))
	PUBLISH_RATE_WINDOW_S = int(os.getenv("PUBLISH_RATE_WINDOW_S", "600"))
	COMMAND_AUDIT_ROOT = os.getenv("COMMAND_AUDIT_ROOT", ".cache/release_notes/audit")

	# Step 11: release publishing
	RELEASE_BACKUPS_ROOT = os.getenv("RELEASE_BACKUPS_ROOT", ".cache/release_notes/release_backups")
	RELEASE_BODY_MAX_CHARS = int(os.getenv("RELEASE_BODY_MAX_CHARS", "250000"))

	# Step 12: guardrails & observability
	CB_FAILURE_THRESHOLD = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
	CB_RECOVERY_TIME_S = int(os.getenv("CB_RECOVERY_TIME_S", "120"))
	CB_HALF_OPEN_MAX_CALLS = int(os.getenv("CB_HALF_OPEN_MAX_CALLS", "1"))
	CB_ROOT = os.getenv("CB_ROOT", ".cache/release_notes/cb")

	WATCHDOG_MAX_RUNTIME_S = int(os.getenv("WATCHDOG_MAX_RUNTIME_S", "300"))

	METRICS_ROOT = os.getenv("METRICS_ROOT", ".cache/release_notes/metrics")
	METRICS_ENABLED = bool(int(os.getenv("METRICS_ENABLED", "1")))

	EMERGENCY_KILL_SWITCH = os.getenv("EMERGENCY_KILL_SWITCH", ".cache/release_notes/KILL")
	ERROR_FEEDBACK_ENABLED = bool(int(os.getenv("ERROR_FEEDBACK_ENABLED", "1")))

	@classmethod
	def get_cb_config(cls) -> Dict[str, int]:
		return {
			"failure_threshold": cls.CB_FAILURE_THRESHOLD,
			"recovery_time_s": cls.CB_RECOVERY_TIME_S,
			"half_open_max_calls": cls.CB_HALF_OPEN_MAX_CALLS,
			"state_root": cls.CB_ROOT,
		}

	@classmethod
	def observability(cls) -> Dict[str, Any]:
		return {
			"metrics_root": cls.METRICS_ROOT,
			"metrics_enabled": cls.METRICS_ENABLED,
			"watchdog_s": cls.WATCHDOG_MAX_RUNTIME_S,
			"kill_switch": cls.EMERGENCY_KILL_SWITCH,
		}
	
	@classmethod
	def get_bedrock_config(cls) -> Dict[str, Any]:
		"""Get Bedrock configuration."""
		return {
			"region_name": cls.AWS_REGION,
			"model_id": cls.BEDROCK_MODEL_ID
		}
	
	@classmethod
	def get_langsmith_config(cls) -> Dict[str, Any]:
		"""Get LangSmith configuration."""
		return {
			"api_key": cls.LANGSMITH_API_KEY,
			"project": cls.LANGSMITH_PROJECT,
			"endpoint": cls.LANGSMITH_ENDPOINT
		}
	
	@classmethod
	def get_github_config(cls) -> Dict[str, Any]:
		"""Get GitHub configuration for MCP and REST clients."""
		return {
			"endpoint": cls.GITHUB_MCP_ENDPOINT,
			"token": cls.GITHUB_TOKEN,
			"timeout_s": cls.HTTP_TIMEOUT_S
		} 

	@classmethod
	def get_diff_budget_config(cls) -> Dict[str, Any]:
		"""Get diff processor budget configuration.
		
		Returns:
			Mapping with soft ratio, hard budget (tokens per chunk), and tokens per char.
		"""
		return {
			"soft_ratio": cls.DIFF_SOFT_BUDGET_RATIO,
			"hard_budget": cls.DIFF_HARD_TOKEN_BUDGET,
			"tokens_per_char": cls.DIFF_TOKENS_PER_CHAR,
		}