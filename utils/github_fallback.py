#!/usr/bin/env python3
"""GitHub REST API fallback client for when MCP tools are unavailable.

This module provides direct GitHub REST API access as a fallback mechanism
when github-mcp-server tools are missing or non-functional. It implements
the same interface as MCP operations to allow seamless switching.
"""

import logging
from typing import Dict, List, Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from configs.config import Config

# Set up logging
logger = logging.getLogger(__name__)


class GithubAuthError(Exception):
    """Raised when GitHub API authentication fails."""
    pass


class GithubApiError(Exception):
    """Raised when GitHub API operations fail."""
    pass


class GithubFallback:
    """Fallback client for GitHub REST API when MCP tools are unavailable."""
    
    def __init__(self, token: Optional[str] = None, timeout_s: Optional[int] = None):
        """Initialize GitHub fallback client.
        
        Args:
            token: GitHub Personal Access Token (defaults to Config.GITHUB_TOKEN)
            timeout_s: Request timeout in seconds (defaults to Config.HTTP_TIMEOUT_S)
            
        Raises:
            GithubAuthError: If no valid token is provided
        """
        github_config = Config.get_github_config()
        self.token = token or github_config["token"]
        self.timeout_s = timeout_s or github_config["timeout_s"]
        self.base_url = "https://api.github.com"
        
        if not self.token:
            raise GithubAuthError("GitHub token is required (GITHUB_TOKEN or GITHUB_PAT env var)")
        
        # Set up session with retries and authentication
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'technical-writer-release-notes-agent/1.0'
        })
        
        # Configure retries for transient failures
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=1,
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        
        logger.info("GitHub fallback client initialized")
    
    def get_repository(self, owner: str, repo: str) -> Dict[str, Any]:
        """Fetch repository metadata via GitHub REST API.
        
        Args:
            owner: Repository owner (user or organization)
            repo: Repository name
            
        Returns:
            Repository metadata dictionary
            
        Raises:
            GithubApiError: If API request fails
        """
        url = f"{self.base_url}/repos/{owner}/{repo}"
        
        try:
            logger.info(f"Fetching repository metadata: {owner}/{repo}")
            response = self.session.get(url, timeout=self.timeout_s)
            
            if response.status_code == 401:
                raise GithubAuthError("Invalid GitHub token or insufficient permissions")
            elif response.status_code == 404:
                raise GithubApiError(f"Repository {owner}/{repo} not found")
            elif response.status_code != 200:
                raise GithubApiError(f"GitHub API error: HTTP {response.status_code}")
            
            data = response.json()
            logger.debug(f"✓ Retrieved repository: {data.get('full_name')}")
            return data
            
        except requests.RequestException as e:
            raise GithubApiError(f"Failed to fetch repository {owner}/{repo}: {e}")
    
    def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        """Fetch pull request metadata via GitHub REST API.
        
        Args:
            owner: Repository owner
            repo: Repository name  
            number: Pull request number
            
        Returns:
            Pull request metadata dictionary
            
        Raises:
            GithubApiError: If API request fails
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{number}"
        
        try:
            logger.info(f"Fetching PR metadata: {owner}/{repo}#{number}")
            response = self.session.get(url, timeout=self.timeout_s)
            
            if response.status_code == 401:
                raise GithubAuthError("Invalid GitHub token or insufficient permissions")
            elif response.status_code == 404:
                raise GithubApiError(f"Pull request {owner}/{repo}#{number} not found")
            elif response.status_code != 200:
                raise GithubApiError(f"GitHub API error: HTTP {response.status_code}")
            
            data = response.json()
            logger.debug(f"✓ Retrieved PR: #{data.get('number')} - {data.get('title', '')[:50]}...")
            return data
            
        except requests.RequestException as e:
            raise GithubApiError(f"Failed to fetch PR {owner}/{repo}#{number}: {e}")
    
    def list_commits_for_pr(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """Fetch commits for a pull request via GitHub REST API.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Pull request number
            
        Returns:
            List of commit metadata dictionaries
            
        Raises:
            GithubApiError: If API request fails
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{number}/commits"
        
        try:
            logger.info(f"Fetching PR commits: {owner}/{repo}#{number}")
            
            # Handle pagination for large PRs
            all_commits = []
            page = 1
            per_page = 100
            
            while True:
                params = {'page': page, 'per_page': per_page}
                response = self.session.get(url, params=params, timeout=self.timeout_s)
                
                if response.status_code == 401:
                    raise GithubAuthError("Invalid GitHub token or insufficient permissions")
                elif response.status_code == 404:
                    raise GithubApiError(f"Pull request {owner}/{repo}#{number} not found")
                elif response.status_code != 200:
                    raise GithubApiError(f"GitHub API error: HTTP {response.status_code}")
                
                page_commits = response.json()
                if not page_commits:  # No more commits
                    break
                    
                all_commits.extend(page_commits)
                page += 1
                
                # Safety limit to prevent infinite loops
                if page > 50:  # Max 5000 commits
                    logger.warning(f"PR #{number} has >5000 commits, truncating for safety")
                    break
            
            logger.debug(f"✓ Retrieved {len(all_commits)} commits for PR #{number}")
            return all_commits
            
        except requests.RequestException as e:
            raise GithubApiError(f"Failed to fetch commits for PR {owner}/{repo}#{number}: {e}")
    
    def get_pull_request_files(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """Fetch file changes for a pull request via GitHub REST API.
        
        Note: GitHub truncates patch content for large files. For Step 3, we'll need
        to use /compare or per-file /contents API for complete diff data.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Pull request number
            
        Returns:
            List of file change dictionaries
            
        Raises:
            GithubApiError: If API request fails
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{number}/files"
        
        try:
            logger.info(f"Fetching PR file changes: {owner}/{repo}#{number}")
            
            # Handle pagination for large PRs
            all_files = []
            page = 1
            per_page = 100
            
            while True:
                params = {'page': page, 'per_page': per_page}
                response = self.session.get(url, params=params, timeout=self.timeout_s)
                
                if response.status_code == 401:
                    raise GithubAuthError("Invalid GitHub token or insufficient permissions")
                elif response.status_code == 404:
                    raise GithubApiError(f"Pull request {owner}/{repo}#{number} not found")
                elif response.status_code != 200:
                    raise GithubApiError(f"GitHub API error: HTTP {response.status_code}")
                
                page_files = response.json()
                if not page_files:  # No more files
                    break
                    
                all_files.extend(page_files)
                page += 1
                
                # Safety limit to prevent infinite loops
                if page > 50:  # Max 5000 files
                    logger.warning(f"PR #{number} has >5000 files, truncating for safety")
                    break
            
            logger.debug(f"✓ Retrieved {len(all_files)} file changes for PR #{number}")
            return all_files
            
        except requests.RequestException as e:
            raise GithubApiError(f"Failed to fetch file changes for PR {owner}/{repo}#{number}: {e}")
    
    def get_file_content(self, owner: str, repo: str, path: str, ref: str = "main") -> Dict[str, Any]:
        """Fetch file content via GitHub REST API.
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: File path in repository
            ref: Git reference (branch, commit, tag)
            
        Returns:
            File content metadata dictionary
            
        Raises:
            GithubApiError: If API request fails
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
        
        try:
            logger.debug(f"Fetching file content: {owner}/{repo}/{path} @ {ref}")
            params = {'ref': ref}
            response = self.session.get(url, params=params, timeout=self.timeout_s)
            
            if response.status_code == 401:
                raise GithubAuthError("Invalid GitHub token or insufficient permissions")
            elif response.status_code == 404:
                raise GithubApiError(f"File {path} not found at {ref}")
            elif response.status_code != 200:
                raise GithubApiError(f"GitHub API error: HTTP {response.status_code}")
            
            data = response.json()
            logger.debug(f"✓ Retrieved file content: {path}")
            return data
            
        except requests.RequestException as e:
            raise GithubApiError(f"Failed to fetch file {owner}/{repo}/{path}: {e}")
    
    def check_rate_limit(self) -> Dict[str, Any]:
        """Check current GitHub API rate limit status.
        
        Returns:
            Rate limit information dictionary
            
        Raises:
            GithubApiError: If API request fails
        """
        url = f"{self.base_url}/rate_limit"
        
        try:
            response = self.session.get(url, timeout=self.timeout_s)
            
            if response.status_code != 200:
                raise GithubApiError(f"Rate limit check failed: HTTP {response.status_code}")
            
            data = response.json()
            
            # Log if rate limit is getting low
            core_remaining = data.get('resources', {}).get('core', {}).get('remaining', 0)
            if core_remaining < 100:
                logger.warning(f"GitHub API rate limit low: {core_remaining} requests remaining")
            
            return data
            
        except requests.RequestException as e:
            raise GithubApiError(f"Failed to check rate limit: {e}")
    
    def close(self) -> None:
        """Close the GitHub client session."""
        if self.session:
            self.session.close()
            logger.debug("GitHub fallback client session closed")


def main():
    """CLI interface for GitHub fallback client testing."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="GitHub Fallback Client")
    parser.add_argument("command", choices=["repo", "pr", "commits", "files"], 
                       help="Command to execute")
    parser.add_argument("owner", help="Repository owner")
    parser.add_argument("repo", help="Repository name")
    parser.add_argument("--number", type=int, help="PR number (for pr, commits, files commands)")
    
    args = parser.parse_args()
    
    # Set up logging for CLI
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        client = GithubFallback()
        
        if args.command == "repo":
            result = client.get_repository(args.owner, args.repo)
            print(f"Repository: {result['full_name']}")
            print(f"Description: {result.get('description', 'N/A')}")
            print(f"Stars: {result.get('stargazers_count', 0)}")
            
        elif args.command in ["pr", "commits", "files"]:
            if not args.number:
                print("Error: --number required for PR commands")
                sys.exit(1)
                
            if args.command == "pr":
                result = client.get_pull_request(args.owner, args.repo, args.number)
                print(f"PR #{result['number']}: {result['title']}")
                print(f"Author: {result['user']['login']}")
                print(f"State: {result['state']}")
                
            elif args.command == "commits":
                result = client.list_commits_for_pr(args.owner, args.repo, args.number)
                print(f"Commits ({len(result)}):")
                for commit in result:
                    sha = commit['sha'][:8]
                    message = commit['commit']['message'].split('\n')[0]
                    print(f"  {sha}: {message}")
                    
            elif args.command == "files":
                result = client.get_pull_request_files(args.owner, args.repo, args.number)
                print(f"File changes ({len(result)}):")
                for file_change in result:
                    status = file_change['status']
                    filename = file_change['filename']
                    changes = file_change.get('changes', 0)
                    print(f"  {status:8} {filename} (+{changes} changes)")
        
        # Check rate limit
        rate_limit = client.check_rate_limit()
        remaining = rate_limit.get('resources', {}).get('core', {}).get('remaining', 'unknown')
        print(f"\nAPI calls remaining: {remaining}")
        
    except (GithubAuthError, GithubApiError) as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
