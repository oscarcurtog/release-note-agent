#!/usr/bin/env python3
"""Pydantic models for pull request data structures.

This module defines the data models used for representing pull request
metadata, commits, and aggregated context in a structured format.
"""

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# Type aliases for better readability
AuthorAssociation = Literal[
    "COLLABORATOR",
    "CONTRIBUTOR", 
    "FIRST_TIMER",
    "FIRST_TIME_CONTRIBUTOR",
    "NONE",
    "MEMBER",
    "OWNER"
]

PRState = Literal["open", "closed"]


class LabelInfo(BaseModel):
    """Information about a GitHub label attached to a PR."""
    
    name: str = Field(..., description="Label name")
    
    model_config = {"extra": "ignore"}


class UserInfo(BaseModel):
    """Basic user information."""
    
    login: str = Field(..., description="GitHub username")
    
    model_config = {"extra": "ignore"}


class PRMetadata(BaseModel):
    """Complete metadata for a pull request."""
    
    number: int = Field(..., description="Pull request number")
    title: str = Field(..., description="Pull request title")
    body: Optional[str] = Field(None, description="Pull request body/description")
    user: UserInfo = Field(..., description="Pull request author")
    labels: List[LabelInfo] = Field(default_factory=list, description="Attached labels")
    state: PRState = Field(..., description="Pull request state")
    author_association: Optional[AuthorAssociation] = Field(
        None, 
        description="Author's association with the repository"
    )
    is_draft: bool = Field(False, description="Whether the PR is a draft")
    base_ref: Optional[str] = Field(None, description="Base branch name")
    head_ref: Optional[str] = Field(None, description="Head branch name")
    base_sha: Optional[str] = Field(None, description="Base commit SHA")
    head_sha: Optional[str] = Field(None, description="Head commit SHA")
    html_url: Optional[str] = Field(None, description="GitHub URL for the PR")
    created_at: Optional[str] = Field(None, description="PR creation timestamp")
    
    model_config = {"extra": "ignore"}


class CommitInfo(BaseModel):
    """Information about a commit in a pull request."""
    
    sha: str = Field(..., description="Commit SHA")
    author_login: Optional[str] = Field(None, description="Commit author GitHub login")
    message: str = Field(..., description="First line of commit message")
    raw_message: Optional[str] = Field(None, description="Full commit message")
    committed_at: Optional[str] = Field(None, description="Commit timestamp")
    
    model_config = {"extra": "ignore"}


class PRContext(BaseModel):
    """Complete context for a pull request including metadata and commits."""
    
    repo: str = Field(..., description="Repository in 'owner/repo' format")
    pr: PRMetadata = Field(..., description="Pull request metadata")
    commits: List[CommitInfo] = Field(default_factory=list, description="List of commits")
    n_commits: int = Field(..., description="Total number of commits")
    routing: Dict[str, str] = Field(
        default_factory=dict,
        description="Routing decisions (MCP vs REST) for observability"
    )
    
    model_config = {"extra": "ignore"}
    
    @classmethod
    def from_pr_and_commits(
        cls,
        repo: str,
        pr_metadata: PRMetadata,
        commits: List[CommitInfo],
        routing: Dict[str, str]
    ) -> "PRContext":
        """Create PRContext from individual components.
        
        Args:
            repo: Repository name in 'owner/repo' format
            pr_metadata: Pull request metadata
            commits: List of commit information
            routing: Routing decisions for observability
            
        Returns:
            Complete PRContext object
        """
        return cls(
            repo=repo,
            pr=pr_metadata,
            commits=commits,
            n_commits=len(commits),
            routing=routing
        )


def normalize_author_association(value: Optional[str]) -> Optional[AuthorAssociation]:
    """Normalize author association string to our enum values.
    
    Args:
        value: Raw author association string from API
        
    Returns:
        Normalized AuthorAssociation value or None if invalid/missing
    """
    if not value or not value.strip():
        return None
        
    # Convert to uppercase and check against valid values
    normalized = value.strip().upper()
    valid_associations = {
        "COLLABORATOR",
        "CONTRIBUTOR", 
        "FIRST_TIMER",
        "FIRST_TIME_CONTRIBUTOR",
        "NONE",
        "MEMBER",
        "OWNER"
    }
    
    return normalized if normalized in valid_associations else None


def extract_first_line(message: str) -> str:
    """Extract the first line of a commit message.
    
    Args:
        message: Full commit message
        
    Returns:
        First line of the message, stripped of whitespace
    """
    if not message:
        return ""
        
    lines = message.splitlines()
    return lines[0].strip() if lines else ""


def safe_extract(data: Dict, *keys, default=None):
    """Safely extract nested dictionary values.
    
    Args:
        data: Dictionary to extract from
        *keys: Sequence of keys to traverse
        default: Default value if path doesn't exist
        
    Returns:
        Value at the nested path or default
        
    Example:
        safe_extract(pr_data, "base", "ref", default="main")
        # Equivalent to pr_data.get("base", {}).get("ref", "main")
    """
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current
