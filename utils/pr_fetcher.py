#!/usr/bin/env python3
"""PR data fetcher utility for aggregating pull request information.

This module provides a thin wrapper around PRDataSource to fetch and normalize
pull request metadata, commits, and file changes in a structured format.
"""

import logging
from typing import Dict, List, Any, Optional

from .pr_data_source import PRDataSource, PRDataSourceError
from .pr_models import (
    PRMetadata, CommitInfo, UserInfo, LabelInfo,
    normalize_author_association, extract_first_line, safe_extract
)
from configs.config import Config

# Set up logging
logger = logging.getLogger(__name__)


class PRFetchError(Exception):
    """Raised when PR fetching operations fail with a typed code for friendly handling."""
    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


class PRFetcher:
    """Fetches and normalizes pull request data using MCP-first, REST fallback strategy."""
    
    def __init__(self, data_source: Optional[PRDataSource] = None):
        """Initialize PR fetcher.
        
        Args:
            data_source: Optional PRDataSource instance. If None, creates a new one.
        """
        self.data_source = data_source or PRDataSource()
        self._initialized = False
        
        # Configuration
        github_config = Config.get_github_config()
        self.timeout_s = github_config["timeout_s"]
        
        logger.info("PR fetcher initialized")
    
    def _ensure_initialized(self) -> None:
        """Ensure the data source is initialized."""
        if not self._initialized:
            try:
                self.data_source.initialize()
                self._initialized = True
                logger.info("PR fetcher data source initialized")
            except PRDataSourceError as e:
                code = getattr(e, "code", "UNKNOWN")
                msg = self._friendly_message_from_code(code, fallback=f"Failed to initialize PR data source: {e}")
                raise PRFetchError(msg, code=code)
    
    def get_pr(self, owner: str, repo: str, pr_number: int) -> PRMetadata:
        """Fetch and normalize pull request metadata.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number
            
        Returns:
            Normalized PRMetadata object
            
        Raises:
            PRFetchError: If fetching fails or PR not found
        """
        self._ensure_initialized()
        
        try:
            logger.info(f"Fetching PR metadata: {owner}/{repo}#{pr_number}")
            pr_data = self.data_source.get_pull_request(owner, repo, pr_number)
            
            # Extract and normalize data
            pr_metadata = self._normalize_pr_data(pr_data)
            
            logger.debug(f"✓ Fetched PR: #{pr_metadata.number} - {pr_metadata.title[:50]}...")
            return pr_metadata
            
        except PRDataSourceError as e:
            code = getattr(e, "code", "UNKNOWN")
            message = self._friendly_message_from_code(
                code,
                fallback=f"Failed to fetch PR {owner}/{repo}#{pr_number}: {e}",
            )
            raise PRFetchError(message, code=code) from e
    
    def list_commits(self, owner: str, repo: str, pr_number: int) -> List[CommitInfo]:
        """Fetch and normalize commits for a pull request.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number
            
        Returns:
            List of normalized CommitInfo objects
            
        Raises:
            PRFetchError: If fetching fails
        """
        self._ensure_initialized()
        
        try:
            logger.info(f"Fetching commits for PR: {owner}/{repo}#{pr_number}")
            commits_data = self.data_source.list_commits_for_pr(owner, repo, pr_number)
            
            # Normalize commits data
            commits = [self._normalize_commit_data(commit) for commit in commits_data]
            
            logger.debug(f"✓ Fetched {len(commits)} commits for PR #{pr_number}")
            return commits
            
        except PRDataSourceError as e:
            code = getattr(e, "code", "UNKNOWN")
            message = self._friendly_message_from_code(
                code,
                fallback=f"Failed to fetch commits for {owner}/{repo}#{pr_number}: {e}",
            )
            raise PRFetchError(message, code=code) from e
    
    def get_files(self, owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetch file changes for a pull request.
        
        Note: This prepares for Step 3 diff processing but does not process diffs yet.
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number
            
        Returns:
            List of file change dictionaries (raw from API)
            
        Raises:
            PRFetchError: If fetching fails
        """
        self._ensure_initialized()
        
        try:
            logger.info(f"Fetching file changes for PR: {owner}/{repo}#{pr_number}")
            files_data = self.data_source.get_pull_request_files(owner, repo, pr_number)
            
            logger.debug(f"✓ Fetched {len(files_data)} file changes for PR #{pr_number}")
            return files_data
            
        except PRDataSourceError as e:
            code = getattr(e, "code", "UNKNOWN")
            message = self._friendly_message_from_code(
                code,
                fallback=f"Failed to fetch file changes for {owner}/{repo}#{pr_number}: {e}",
            )
            raise PRFetchError(message, code=code) from e
    
    def get_routing_info(self) -> Dict[str, str]:
        """Get routing information for observability.
        
        Returns:
            Dictionary mapping operations to their routing method (MCP vs REST)
        """
        if not self._initialized:
            return {"status": "not_initialized"}
            
        try:
            capability_summary = self.data_source.get_capability_summary()
            return capability_summary.get("routing", {})
        except Exception as e:
            logger.warning(f"Failed to get routing info: {e}")
            return {"error": str(e)}
    
    def _normalize_pr_data(self, pr_data: Dict[str, Any]) -> PRMetadata:
        """Normalize raw PR data into PRMetadata model.
        
        Args:
            pr_data: Raw PR data from API
            
        Returns:
            Normalized PRMetadata object
        """
        # Extract user information
        user_data = pr_data.get("user", {})
        user = UserInfo(login=user_data.get("login", "unknown"))
        
        # Extract and normalize labels
        labels_data = pr_data.get("labels") or []
        labels = [LabelInfo(name=label.get("name", "")) for label in labels_data if label.get("name")]
        
        # Normalize author association
        raw_association = pr_data.get("author_association")
        author_association = normalize_author_association(raw_association)
        
        # Extract base and head information
        base_ref = safe_extract(pr_data, "base", "ref")
        head_ref = safe_extract(pr_data, "head", "ref")
        base_sha = safe_extract(pr_data, "base", "sha")
        head_sha = safe_extract(pr_data, "head", "sha")
        
        return PRMetadata(
            number=pr_data.get("number", 0),
            title=pr_data.get("title", ""),
            body=pr_data.get("body"),
            user=user,
            labels=labels,
            state=pr_data.get("state", "open"),
            author_association=author_association,
            is_draft=bool(pr_data.get("draft", False)),
            base_ref=base_ref,
            head_ref=head_ref,
            base_sha=base_sha,
            head_sha=head_sha,
            html_url=pr_data.get("html_url"),
            created_at=pr_data.get("created_at")
        )
    
    def _normalize_commit_data(self, commit_data: Dict[str, Any]) -> CommitInfo:
        """Normalize raw commit data into CommitInfo model.
        
        Args:
            commit_data: Raw commit data from API
            
        Returns:
            Normalized CommitInfo object
        """
        # Extract commit details
        commit_info = commit_data.get("commit", {})
        raw_message = commit_info.get("message", "")
        
        # Extract author login - prefer GitHub user, fallback to commit author name
        author_login = None
        if "author" in commit_data and commit_data["author"]:
            author_login = commit_data["author"].get("login")
        
        if not author_login:
            # Fallback to commit author name (not ideal but better than None)
            commit_author = commit_info.get("author", {})
            author_name = commit_author.get("name")
            if author_name and author_name != "unknown":
                author_login = author_name
        
        return CommitInfo(
            sha=commit_data.get("sha", ""),
            author_login=author_login,
            message=extract_first_line(raw_message),
            raw_message=raw_message,
            committed_at=safe_extract(commit_info, "author", "date")
        )
    
    def _friendly_message_from_code(self, code: str, *, fallback: str) -> str:
        mapping = {
            "TIMEOUT": "Timeout while fetching data. Please retry or increase HTTP_TIMEOUT_S.",
            "NOT_FOUND": "PR not found. Please check repository name and PR number.",
            "UNAUTHORIZED": "Access denied. Please check your GitHub token and its scopes.",
            "RATE_LIMIT": "Rate limit exceeded. Please wait a few minutes and retry.",
            "NETWORK": "Network error while contacting GitHub. Please retry.",
        }
        return mapping.get(code, fallback)
    
    def close(self) -> None:
        """Close the PR fetcher and cleanup resources."""
        if self.data_source:
            self.data_source.close()
        logger.info("PR fetcher closed")


def main():
    """CLI interface for PR fetcher testing."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="PR Fetcher Test Tool")
    parser.add_argument("command", choices=["pr", "commits", "files"], help="Command to execute")
    parser.add_argument("owner", help="Repository owner")
    parser.add_argument("repo", help="Repository name")
    parser.add_argument("number", type=int, help="PR number")
    
    args = parser.parse_args()
    
    # Set up logging for CLI
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        fetcher = PRFetcher()
        
        if args.command == "pr":
            pr_metadata = fetcher.get_pr(args.owner, args.repo, args.number)
            print(f"PR #{pr_metadata.number}: {pr_metadata.title}")
            print(f"Author: {pr_metadata.user.login}")
            print(f"State: {pr_metadata.state}")
            print(f"Labels: {[label.name for label in pr_metadata.labels]}")
            
        elif args.command == "commits":
            commits = fetcher.list_commits(args.owner, args.repo, args.number)
            print(f"Commits ({len(commits)}):")
            for commit in commits:
                sha = commit.sha[:8]
                author = commit.author_login or "unknown"
                print(f"  {sha} ({author}): {commit.message}")
                
        elif args.command == "files":
            files = fetcher.get_files(args.owner, args.repo, args.number)
            print(f"File changes ({len(files)}):")
            for file_change in files[:10]:  # Show first 10
                status = file_change.get("status", "unknown")
                filename = file_change.get("filename", "unknown")
                print(f"  {status:8} {filename}")
        
        # Show routing info
        routing = fetcher.get_routing_info()
        print(f"\nRouting: {routing}")
        
    except PRFetchError as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        fetcher.close()


if __name__ == "__main__":
    main()
