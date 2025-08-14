#!/usr/bin/env python3
"""Pull request data source abstraction layer.

This module provides a unified interface for fetching PR data using either
github-mcp-server or GitHub REST API fallback, depending on tool availability.
It handles the routing logic and provides consistent data structures.
"""

import logging
from typing import Dict, List, Any, Optional

from .mcp_client import MCPClient, MCPAuthError, MCPCapabilityError
from .github_fallback import GithubFallback, GithubAuthError, GithubApiError
from configs.config import Config

# Set up logging
logger = logging.getLogger(__name__)


class PRDataSourceError(Exception):
    """Raised when PR data source operations fail with a typed code."""
    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


class PRDataSource:
    """Unified data source for pull request information with MCP-first, REST fallback strategy."""
    
    def __init__(self, token: Optional[str] = None):
        """Initialize PR data source with authentication.
        
        Args:
            token: GitHub Personal Access Token (defaults to Config.GITHUB_TOKEN)
            
        Raises:
            PRDataSourceError: If initialization fails
        """
        github_config = Config.get_github_config()
        self.token = token or github_config["token"]
        if not self.token:
            raise PRDataSourceError("GitHub token is required (GITHUB_TOKEN or GITHUB_PAT env var)", code="UNAUTHORIZED")
        
        self.mcp_client: Optional[MCPClient] = None
        self.github_client: Optional[GithubFallback] = None
        self.capabilities: Optional[Dict[str, bool]] = None
        self._initialized = False
        
        logger.info("PR data source initialized")
    
    def initialize(self) -> None:
        """Initialize and probe both MCP and GitHub clients.
        
        Raises:
            PRDataSourceError: If both MCP and GitHub clients fail to initialize
        """
        if self._initialized:
            return
            
        mcp_available = False
        github_available = False
        
        # Try to initialize MCP client first
        try:
            self.mcp_client = MCPClient()
            github_config = Config.get_github_config()
            self.mcp_client.connect(
                github_config["endpoint"],
                self.token,
                github_config["timeout_s"]
            )
            self.capabilities = self.mcp_client.probe_tools()
            mcp_available = True
            logger.info("✓ MCP client initialized successfully")
            
        except (MCPAuthError, MCPCapabilityError) as e:
            logger.warning(f"MCP client initialization failed: {e}")
            self.mcp_client = None
            self.capabilities = {}
        
        # Initialize GitHub fallback client
        try:
            self.github_client = GithubFallback(self.token)
            github_available = True
            logger.info("✓ GitHub fallback client initialized")
            
        except (GithubAuthError, GithubApiError) as e:
            logger.error(f"GitHub fallback client initialization failed: {e}")
            self.github_client = None
        
        # Check if at least one client is available
        if not mcp_available and not github_available:
            raise PRDataSourceError("Both MCP and GitHub REST clients failed to initialize")
        
        if not mcp_available:
            logger.warning("Operating in GitHub REST-only mode (MCP unavailable)")
        elif not github_available:
            logger.warning("Operating in MCP-only mode (GitHub REST unavailable)")
        
        self._initialized = True
        
        # Log capability summary
        if self.capabilities:
            available_count = sum(self.capabilities.values())
            total_count = len(self.capabilities)
            fallback_tools = [k for k, v in self.capabilities.items() if not v]
            
            if fallback_tools:
                logger.info(f"PR data source ready: MCP tools {available_count}/{total_count}; "
                          f"fallback needed for: {', '.join(fallback_tools)}")
            else:
                logger.info(f"PR data source ready: MCP tools {available_count}/{total_count} (full capability)")
        else:
            logger.info("PR data source ready: GitHub REST-only mode")
            
        logger.info("PR data source initialization complete")
    
    def get_repository(self, owner: str, repo: str) -> Dict[str, Any]:
        """Fetch repository metadata using best available method.
        
        Args:
            owner: Repository owner
            repo: Repository name
            
        Returns:
            Repository metadata dictionary
            
        Raises:
            PRDataSourceError: If all methods fail
        """
        self._ensure_initialized()
        
        # Try MCP first if available
        if self.mcp_client and self.capabilities.get("get_repository", False):
            try:
                logger.debug(f"Fetching repository via MCP: {owner}/{repo}")
                # TODO: Implement actual MCP call in Step 2
                # For now, fallback to GitHub REST
                raise NotImplementedError("MCP repository fetch not implemented yet")
                
            except NotImplementedError:
                logger.info(f"MCP get_repository not yet implemented, falling back to REST for {owner}/{repo}")
            except Exception as e:
                logger.warning(f"MCP repository fetch failed: {e}, falling back to REST")
        
        # Fallback to GitHub REST API
        if self.github_client:
            try:
                logger.debug(f"Fetching repository via REST: {owner}/{repo}")
                return self.github_client.get_repository(owner, repo)
                
            except GithubAuthError as e:
                raise PRDataSourceError(f"Failed to fetch repository {owner}/{repo}: {e}", code="UNAUTHORIZED")
            except GithubApiError as e:
                code = self._map_api_error_to_code(str(e))
                raise PRDataSourceError(f"Failed to fetch repository {owner}/{repo}: {e}", code=code)
        
        raise PRDataSourceError("No available method to fetch repository data")
    
    def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        """Fetch pull request metadata using best available method.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Pull request number
            
        Returns:
            Pull request metadata dictionary
            
        Raises:
            PRDataSourceError: If all methods fail
        """
        self._ensure_initialized()
        
        # Try MCP first if available
        if self.mcp_client and self.capabilities.get("get_pull_request", False):
            try:
                logger.debug(f"Fetching PR via MCP: {owner}/{repo}#{number}")
                # TODO: Implement actual MCP call in Step 2
                # For now, fallback to GitHub REST
                raise NotImplementedError("MCP PR fetch not implemented yet")
                
            except NotImplementedError:
                logger.info(f"MCP get_pull_request not yet implemented, falling back to REST for {owner}/{repo}#{number}")
            except Exception as e:
                logger.warning(f"MCP PR fetch failed: {e}, falling back to REST")
        
        # Fallback to GitHub REST API
        if self.github_client:
            try:
                logger.debug(f"Fetching PR via REST: {owner}/{repo}#{number}")
                return self.github_client.get_pull_request(owner, repo, number)
                
            except GithubAuthError as e:
                raise PRDataSourceError(f"Failed to fetch PR {owner}/{repo}#{number}: {e}", code="UNAUTHORIZED")
            except GithubApiError as e:
                code = self._map_api_error_to_code(str(e))
                raise PRDataSourceError(f"Failed to fetch PR {owner}/{repo}#{number}: {e}", code=code)
        
        raise PRDataSourceError("No available method to fetch pull request data")
    
    def list_commits_for_pr(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """Fetch commits for a pull request using best available method.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Pull request number
            
        Returns:
            List of commit metadata dictionaries
            
        Raises:
            PRDataSourceError: If all methods fail
        """
        self._ensure_initialized()
        
        # Try MCP first if available
        if self.mcp_client and self.capabilities.get("list_commits_for_pr", False):
            try:
                logger.debug(f"Fetching PR commits via MCP: {owner}/{repo}#{number}")
                # TODO: Implement actual MCP call in Step 2
                # For now, fallback to GitHub REST
                raise NotImplementedError("MCP commits fetch not implemented yet")
                
            except NotImplementedError:
                logger.info(f"MCP list_commits_for_pr not yet implemented, falling back to REST for {owner}/{repo}#{number}")
            except Exception as e:
                logger.warning(f"MCP commits fetch failed: {e}, falling back to REST")
        
        # Fallback to GitHub REST API
        if self.github_client:
            try:
                logger.debug(f"Fetching PR commits via REST: {owner}/{repo}#{number}")
                return self.github_client.list_commits_for_pr(owner, repo, number)
                
            except GithubAuthError as e:
                raise PRDataSourceError(f"Failed to fetch commits for PR {owner}/{repo}#{number}: {e}", code="UNAUTHORIZED")
            except GithubApiError as e:
                code = self._map_api_error_to_code(str(e))
                raise PRDataSourceError(f"Failed to fetch commits for PR {owner}/{repo}#{number}: {e}", code=code)
        
        raise PRDataSourceError("No available method to fetch commit data")
    
    def get_pull_request_files(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """Fetch file changes for a pull request using best available method.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Pull request number
            
        Returns:
            List of file change dictionaries
            
        Raises:
            PRDataSourceError: If all methods fail
        """
        self._ensure_initialized()
        
        # Try MCP first if available (unified_diff or get_file_content)
        if self.mcp_client and (self.capabilities.get("unified_diff", False) or 
                                self.capabilities.get("get_file_content", False)):
            try:
                logger.debug(f"Fetching PR files via MCP: {owner}/{repo}#{number}")
                # TODO: Implement actual MCP call in Step 2
                # For now, fallback to GitHub REST
                raise NotImplementedError("MCP file changes fetch not implemented yet")
                
            except NotImplementedError:
                logger.info(f"MCP file operations not yet implemented, falling back to REST for {owner}/{repo}#{number}")
            except Exception as e:
                logger.warning(f"MCP file changes fetch failed: {e}, falling back to REST")
        
        # Fallback to GitHub REST API
        if self.github_client:
            try:
                logger.debug(f"Fetching PR files via REST: {owner}/{repo}#{number}")
                return self.github_client.get_pull_request_files(owner, repo, number)
                
            except GithubAuthError as e:
                raise PRDataSourceError(f"Failed to fetch file changes for PR {owner}/{repo}#{number}: {e}", code="UNAUTHORIZED")
            except GithubApiError as e:
                code = self._map_api_error_to_code(str(e))
                raise PRDataSourceError(f"Failed to fetch file changes for PR {owner}/{repo}#{number}: {e}", code=code)
        
        raise PRDataSourceError("No available method to fetch file change data")
    
    def get_capability_summary(self) -> Dict[str, Any]:
        """Get a summary of available capabilities and routing decisions.
        
        Returns:
            Dictionary with capability information and routing details
        """
        self._ensure_initialized()
        
        summary = {
            "mcp_available": self.mcp_client is not None,
            "github_available": self.github_client is not None,
            "capabilities": self.capabilities or {},
            "routing": {}
        }
        
        # Determine routing for each operation
        operations = ["get_repository", "get_pull_request", "list_commits_for_pr", "get_file_content"]
        
        for op in operations:
            if self.mcp_client and self.capabilities.get(op, False):
                summary["routing"][op] = "mcp"
            elif self.github_client:
                summary["routing"][op] = "github_rest"
            else:
                summary["routing"][op] = "unavailable"
        
        # Special case for file changes (can use multiple MCP tools)
        if self.mcp_client and (self.capabilities.get("unified_diff", False) or 
                                self.capabilities.get("get_file_content", False)):
            summary["routing"]["get_pull_request_files"] = "mcp"
        elif self.github_client:
            summary["routing"]["get_pull_request_files"] = "github_rest"
        else:
            summary["routing"]["get_pull_request_files"] = "unavailable"
        
        return summary
    
    def close(self) -> None:
        """Close all client sessions and cleanup resources."""
        if self.mcp_client:
            self.mcp_client.close()
        
        if self.github_client:
            self.github_client.close()
            
        logger.info("PR data source closed")
    
    def _ensure_initialized(self) -> None:
        """Ensure the data source is properly initialized.
        
        Raises:
            PRDataSourceError: If not initialized
        """
        if not self._initialized:
            raise PRDataSourceError("Must call initialize() before using PR data source", code="UNKNOWN")

    def _map_api_error_to_code(self, message: str) -> str:
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


def main():
    """CLI interface for PR data source testing."""
    import argparse
    import sys
    import json
    
    parser = argparse.ArgumentParser(description="PR Data Source Test")
    parser.add_argument("command", choices=["capabilities", "repo", "pr", "commits", "files"], 
                       help="Command to execute")
    parser.add_argument("owner", nargs="?", help="Repository owner")
    parser.add_argument("repo", nargs="?", help="Repository name")
    parser.add_argument("--number", type=int, help="PR number")
    
    args = parser.parse_args()
    
    # Set up logging for CLI
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        data_source = PRDataSource()
        data_source.initialize()
        
        if args.command == "capabilities":
            capabilities = data_source.get_capability_summary()
            print(json.dumps(capabilities, indent=2))
            
        elif args.command in ["repo", "pr", "commits", "files"]:
            if not args.owner or not args.repo:
                print("Error: owner and repo arguments required")
                sys.exit(1)
                
            if args.command == "repo":
                result = data_source.get_repository(args.owner, args.repo)
                print(f"Repository: {result['full_name']}")
                print(f"Description: {result.get('description', 'N/A')}")
                
            elif args.command in ["pr", "commits", "files"]:
                if not args.number:
                    print("Error: --number required for PR commands")
                    sys.exit(1)
                    
                if args.command == "pr":
                    result = data_source.get_pull_request(args.owner, args.repo, args.number)
                    print(f"PR #{result['number']}: {result['title']}")
                    print(f"Author: {result['user']['login']}")
                    
                elif args.command == "commits":
                    result = data_source.list_commits_for_pr(args.owner, args.repo, args.number)
                    print(f"Commits: {len(result)}")
                    for commit in result[:5]:  # Show first 5
                        print(f"  {commit['sha'][:8]}: {commit['commit']['message'].split()[0]}")
                        
                elif args.command == "files":
                    result = data_source.get_pull_request_files(args.owner, args.repo, args.number)
                    print(f"File changes: {len(result)}")
                    for file_change in result[:10]:  # Show first 10
                        print(f"  {file_change['status']}: {file_change['filename']}")
        
    except PRDataSourceError as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        data_source.close()


if __name__ == "__main__":
    main()
