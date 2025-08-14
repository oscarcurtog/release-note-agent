#!/usr/bin/env python3
"""MCP client wrapper for github-mcp-server integration.

This module provides a client for connecting to github-mcp-server and probing
available tools. It handles authentication, capability discovery, and graceful
error handling for MCP operations.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Any
from pathlib import Path

import requests

from configs.config import Config

# Set up logging
logger = logging.getLogger(__name__)

# Define capability cache file (ignored by git)
CAPABILITY_CACHE_FILE = ".mcp-capabilities.json"


class MCPAuthError(Exception):
    """Raised when MCP authentication fails."""
    pass


class MCPCapabilityError(Exception):
    """Raised when MCP tool capability detection fails."""
    pass


@dataclass
class ToolCapabilities:
    """Data structure for MCP tool availability mapping."""
    get_repository: bool = False
    get_pull_request: bool = False
    list_commits_for_pr: bool = False
    get_file_content: bool = False
    unified_diff: bool = False
    last_updated: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "get_repository": self.get_repository,
            "get_pull_request": self.get_pull_request,
            "list_commits_for_pr": self.list_commits_for_pr,
            "get_file_content": self.get_file_content,
            "unified_diff": self.unified_diff,
            "last_updated": self.last_updated
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCapabilities":
        """Create from dictionary (JSON deserialization)."""
        return cls(
            get_repository=data.get("get_repository", False),
            get_pull_request=data.get("get_pull_request", False),
            list_commits_for_pr=data.get("list_commits_for_pr", False),
            get_file_content=data.get("get_file_content", False),
            unified_diff=data.get("unified_diff", False),
            last_updated=data.get("last_updated")
        )


class MCPClient:
    """Client for github-mcp-server integration with tool discovery and fallback handling."""
    
    def __init__(self):
        """Initialize MCP client."""
        self.endpoint: Optional[str] = None
        self.token: Optional[str] = None
        self.session: Optional[requests.Session] = None
        self.capabilities: Optional[ToolCapabilities] = None
        self.timeout_s: int = Config.HTTP_TIMEOUT_S
        
    def connect(self, endpoint: str, token: str, timeout_s: int = 30) -> None:
        """Connect to github-mcp-server with authentication.
        
        Args:
            endpoint: MCP server endpoint URL
            token: GitHub Personal Access Token
            timeout_s: Request timeout in seconds
            
        Raises:
            MCPAuthError: If authentication fails
            ValueError: If endpoint or token is invalid
        """
        if not endpoint or not endpoint.strip():
            raise ValueError("MCP endpoint cannot be empty")
        
        if not token or not token.strip():
            raise MCPAuthError("GitHub token is required for MCP authentication")
            
        self.endpoint = endpoint.rstrip('/')
        self.token = token
        self.timeout_s = timeout_s
        
        # Create authenticated session
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'technical-writer-release-notes-agent/1.0'
        })
        
        # Test authentication with a simple endpoint
        try:
            logger.info(f"Authenticating with MCP server at {self._redact_url(self.endpoint)}")
            response = self.session.get(
                f"{self.endpoint}/health", 
                timeout=self.timeout_s
            )
            
            if response.status_code == 401:
                raise MCPAuthError("Invalid GitHub token or insufficient permissions")
            elif response.status_code >= 400:
                raise MCPAuthError(f"MCP authentication failed: HTTP {response.status_code}")
                
            logger.info("✓ MCP authentication successful")
            
        except requests.RequestException as e:
            raise MCPAuthError(f"Failed to connect to MCP server: {e}")
    
    def probe_tools(self) -> Dict[str, bool]:
        """Probe available MCP tools and return capability mapping.
        
        Returns:
            Dictionary mapping tool names to availability (bool)
            
        Raises:
            MCPCapabilityError: If tool discovery fails
        """
        if not self.session:
            raise MCPCapabilityError("Must connect() before probing tools")
            
        logger.info("Probing MCP tool capabilities...")
        
        # Tools we need for release-notes agent
        target_tools = [
            "get_repository",
            "get_pull_request", 
            "list_commits_for_pr",
            "get_file_content",
            "unified_diff"  # This might not exist, expect fallback
        ]
        
        capabilities_map = {}
        
        try:
            # Probe each tool by attempting to list available tools or making test calls
            # For MVP, we'll use a simple endpoint check approach
            tools_endpoint = f"{self.endpoint}/tools"
            response = self.session.get(tools_endpoint, timeout=self.timeout_s)
            
            if response.status_code == 200:
                available_tools = response.json().get('tools', [])
                tool_names = [tool.get('name', '') for tool in available_tools]
                
                for tool in target_tools:
                    is_available = tool in tool_names
                    capabilities_map[tool] = is_available
                    status = "✓" if is_available else "✗"
                    logger.info(f"  {tool}: {status}")
                    
            else:
                # Fallback: individual tool testing
                logger.warning(f"Tools endpoint unavailable (HTTP {response.status_code}), testing individual tools")
                for tool in target_tools:
                    is_available = self._test_tool_availability(tool)
                    capabilities_map[tool] = is_available
                    status = "✓" if is_available else "✗"
                    logger.info(f"  {tool}: {status}")
                    
        except requests.RequestException as e:
            raise MCPCapabilityError(f"Failed to probe MCP tools: {e}")
        
        # Create capabilities object and cache it
        self.capabilities = ToolCapabilities(
            get_repository=capabilities_map.get("get_repository", False),
            get_pull_request=capabilities_map.get("get_pull_request", False),
            list_commits_for_pr=capabilities_map.get("list_commits_for_pr", False),
            get_file_content=capabilities_map.get("get_file_content", False),
            unified_diff=capabilities_map.get("unified_diff", False),
            last_updated=time.time()
        )
        
        # Cache the results
        self._cache_capabilities(self.capabilities)
        
        # Log summary
        available_count = sum(capabilities_map.values())
        total_count = len(capabilities_map)
        fallback_tools = [k for k, v in capabilities_map.items() if not v]
        
        if fallback_tools:
            logger.warning(f"MCP tools: {available_count}/{total_count} available; "
                         f"fallback needed for: {', '.join(fallback_tools)}")
        else:
            logger.info(f"MCP tools: {available_count}/{total_count} available (full capability)")
            
        return capabilities_map
    
    def has(self, tool_name: str) -> bool:
        """Check if a specific MCP tool is available.
        
        Args:
            tool_name: Name of the tool to check
            
        Returns:
            True if tool is available, False otherwise
        """
        if not self.capabilities:
            logger.warning("Tool capabilities not probed yet, returning False")
            return False
            
        return getattr(self.capabilities, tool_name, False)
    
    def close(self) -> None:
        """Close the MCP client session and cleanup resources."""
        if self.session:
            self.session.close()
            self.session = None
            logger.info("MCP client session closed")
    
    def _test_tool_availability(self, tool_name: str) -> bool:
        """Test if a specific tool is available by making a minimal test call.
        
        Args:
            tool_name: Name of the tool to test
            
        Returns:
            True if tool responds successfully, False otherwise
        """
        try:
            # Make a lightweight test call for each tool
            test_endpoint = f"{self.endpoint}/tools/{tool_name}/test"
            response = self.session.head(test_endpoint, timeout=5)
            return response.status_code < 400
            
        except requests.RequestException:
            return False
    
    def _cache_capabilities(self, capabilities: ToolCapabilities) -> None:
        """Cache capabilities to local file for faster subsequent loads.
        
        Args:
            capabilities: ToolCapabilities object to cache
        """
        try:
            cache_path = Path(CAPABILITY_CACHE_FILE)
            with cache_path.open('w') as f:
                json.dump(capabilities.to_dict(), f, indent=2)
            logger.debug(f"Cached capabilities to {cache_path}")
            
        except Exception as e:
            logger.warning(f"Failed to cache capabilities: {e}")
    
    def _load_cached_capabilities(self) -> Optional[ToolCapabilities]:
        """Load capabilities from cache if available and recent.
        
        Returns:
            ToolCapabilities if cache is valid, None otherwise
        """
        try:
            cache_path = Path(CAPABILITY_CACHE_FILE)
            if not cache_path.exists():
                return None
                
            with cache_path.open('r') as f:
                data = json.load(f)
                
            capabilities = ToolCapabilities.from_dict(data)
            
            # Check if cache is recent (within 1 hour)
            if capabilities.last_updated:
                age_hours = (time.time() - capabilities.last_updated) / 3600
                if age_hours < 1:
                    logger.debug("Using cached MCP capabilities")
                    return capabilities
                    
            return None
            
        except Exception as e:
            logger.warning(f"Failed to load cached capabilities: {e}")
            return None
    
    def _redact_url(self, url: str) -> str:
        """Redact sensitive information from URLs for logging.
        
        Args:
            url: URL to redact
            
        Returns:
            URL with sensitive parts redacted
        """
        # Simple redaction - just show domain
        if '://' in url:
            protocol, rest = url.split('://', 1)
            domain = rest.split('/')[0]
            return f"{protocol}://{domain}/..."
        return url


def main():
    """CLI interface for MCP client testing and capability probing."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="MCP Client Tool")
    parser.add_argument("--probe", action="store_true", help="Probe MCP tool capabilities")
    parser.add_argument("owner", nargs="?", help="GitHub repository owner")
    parser.add_argument("repo", nargs="?", help="GitHub repository name")
    
    args = parser.parse_args()
    
    # Set up logging for CLI
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if args.probe:
        if not args.owner or not args.repo:
            print("Error: --probe requires owner and repo arguments")
            sys.exit(1)
            
        # Get configuration
        github_config = Config.get_github_config()
        endpoint = github_config["endpoint"]
        token = github_config["token"]
        
        if not token:
            print("Error: GITHUB_TOKEN or GITHUB_PAT environment variable required")
            sys.exit(1)
            
        # Create and test client
        client = MCPClient()
        try:
            client.connect(endpoint, token)
            capabilities = client.probe_tools()
            
            print(f"\nMCP Capability Report for {args.owner}/{args.repo}:")
            print("=" * 50)
            for tool, available in capabilities.items():
                status = "✓ Available" if available else "✗ Fallback needed"
                print(f"{tool:20} : {status}")
                
        except (MCPAuthError, MCPCapabilityError) as e:
            print(f"Error: {e}")
            sys.exit(1)
        finally:
            client.close()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
