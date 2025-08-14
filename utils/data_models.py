from enum import Enum
from typing import List
from pydantic import BaseModel, Field

class SeverityLevel(str, Enum):
    """Severity levels for gap analysis issues."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class GapIssue(BaseModel):
    """Individual gap analysis issue."""
    issue_type: str = Field(..., description="Type of issue: missing, divergent, inconsistent, or structural")
    description: str = Field(..., description="Clear description of the issue")
    severity: SeverityLevel = Field(..., description="Severity level of the issue")
    line_references: List[str] = Field(..., description="List of line numbers or sections where the issue occurs")
    section: str = Field(..., description="The specific section or component affected")
    recommendation: str = Field(..., description="How to fix the issue")

class GapReport(BaseModel):
    """Complete gap analysis report."""
    md_file: str = Field(..., description="Name of the Markdown file")
    rosetta_file: str = Field(..., description="Name of the Rosetta file")
    total_issues: int = Field(..., description="Total number of issues found")
    critical_issues: int = Field(..., description="Number of critical issues")
    high_issues: int = Field(..., description="Number of high severity issues")
    medium_issues: int = Field(..., description="Number of medium severity issues")
    low_issues: int = Field(..., description="Number of low severity issues")
    issues: List[GapIssue] = Field(..., description="List of all issues found")
    summary: str = Field(..., description="Summary of the analysis")
    
    class Config:
        json_encoders = {
            SeverityLevel: lambda v: v.value
        }

class StructuredGapAnalysis(BaseModel):
    """
    Structured output model for gap analysis responses.
    
    This model is specifically designed for structured output from the LLM,
    containing only the fields that the LLM should return.
    """
    total_issues: int = Field(..., description="Total number of issues found")
    critical_issues: int = Field(..., description="Number of critical severity issues")
    high_issues: int = Field(..., description="Number of high severity issues")
    medium_issues: int = Field(..., description="Number of medium severity issues")
    low_issues: int = Field(..., description="Number of low severity issues")
    issues: List[GapIssue] = Field(..., description="List of all issues found")
    summary: str = Field(..., description="Summary of the analysis")
    
    def to_gap_report(self, md_file: str, rosetta_file: str) -> GapReport:
        """
        Convert to a full GapReport with file information.
        
        Args:
            md_file: Name of the Markdown file
            rosetta_file: Name of the Rosetta file
            
        Returns:
            Complete GapReport object
        """
        return GapReport(
            md_file=md_file,
            rosetta_file=rosetta_file,
            total_issues=self.total_issues,
            critical_issues=self.critical_issues,
            high_issues=self.high_issues,
            medium_issues=self.medium_issues,
            low_issues=self.low_issues,
            issues=self.issues,
            summary=self.summary
        ) 