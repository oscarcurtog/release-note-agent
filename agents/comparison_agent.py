import os
import json
from typing import Dict, Any, List, Tuple, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from utils.bedrock_client import BedrockClient
from utils.structured_output import StructuredOutputClient, StructuredOutputError
from utils.data_models import GapReport, GapIssue, SeverityLevel, StructuredGapAnalysis
from configs.config import Config

class AgentState(BaseModel):
    """State for the comparison agent workflow."""
    md_file: str
    rosetta_file: str
    md_content: str = ""
    rosetta_content: str = ""
    analysis_result: Optional[StructuredGapAnalysis] = None
    gap_report: Optional[GapReport] = None
    error: str = ""

class ComparisonAgent:
    """Agent for comparing Markdown and Rosetta files."""
    
    def __init__(self):
        """Initialize the comparison agent."""
        self.bedrock_client = BedrockClient()
        self.structured_client = StructuredOutputClient(self.bedrock_client)
    

    
    def _load_files(self, state: AgentState) -> AgentState:
        """Load the content of both files."""
        try:
            # Load Markdown file
            md_path = os.path.join(Config.FILES_DIR, state.md_file)
            if not os.path.exists(md_path):
                raise FileNotFoundError(f"Markdown file not found: {md_path}")
            
            with open(md_path, 'r', encoding='utf-8') as f:
                state.md_content = f.read()
            
            # Load Rosetta file
            rosetta_path = os.path.join(Config.FILES_DIR, state.rosetta_file)
            if not os.path.exists(rosetta_path):
                raise FileNotFoundError(f"Rosetta file not found: {rosetta_path}")
            
            with open(rosetta_path, 'r', encoding='utf-8') as f:
                state.rosetta_content = f.read()
                
        except Exception as e:
            state.error = f"Error loading files: {str(e)}"
        
        # Ensure we return the state object, not a dict
        return AgentState(**state.model_dump())
    
    def _analyze_content(self, state: AgentState) -> AgentState:
        """Analyze the content using Bedrock with structured output."""
        try:
            if state.error:
                return AgentState(**state.model_dump())
            
            # Load the prompt template
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', 'gap_analyst.prompt')
            with open(prompt_path, 'r') as f:
                prompt_template = f.read()
            
            # Format the prompt
            prompt = prompt_template.format(md_content=state.md_content, rosetta_content=state.rosetta_content)
            
            # Use structured output to get validated response
            try:
                state.analysis_result = self.structured_client.create_with_fallback(
                    model_class=StructuredGapAnalysis,
                    prompt=prompt,
                    max_tokens=4000
                )
            except StructuredOutputError as e:
                state.error = f"Structured output failed: {str(e)}"
            
        except Exception as e:
            state.error = f"Error analyzing content: {str(e)}"
        
        # Ensure we return the state object, not a dict
        return AgentState(**state.model_dump())
    
    def _parse_results(self, state: AgentState) -> AgentState:
        """Convert structured analysis results to a gap report."""
        try:
            if state.error:
                return AgentState(**state.model_dump())
            
            # Check if we have analysis results
            if not state.analysis_result:
                state.error = "No analysis results received from Bedrock"
                return AgentState(**state.model_dump())
            
            # Convert structured analysis to gap report
            state.gap_report = state.analysis_result.to_gap_report(
                md_file=state.md_file,
                rosetta_file=state.rosetta_file
            )
            
        except Exception as e:
            state.error = f"Error parsing results: {str(e)}"
        
        # Ensure we return the state object, not a dict
        return AgentState(**state.model_dump())
    
    def compare_files(self, md_file: str, rosetta_file: str) -> GapReport:
        """
        Compare a pair of Markdown and Rosetta files.
        
        Args:
            md_file: Name of the Markdown file
            rosetta_file: Name of the Rosetta file
            
        Returns:
            GapReport object with analysis results
        """
        # Initialize the state
        state = AgentState(
            md_file=md_file,
            rosetta_file=rosetta_file
        )
        
        # Run the workflow steps directly
        try:
            # Step 1: Load files
            state = self._load_files(state)
            if state.error:
                raise Exception(state.error)
            
            # Step 2: Analyze content
            state = self._analyze_content(state)
            if state.error:
                raise Exception(state.error)
            
            # Step 3: Parse results
            state = self._parse_results(state)
            if state.error:
                raise Exception(state.error)
            
            return state.gap_report
            
        except Exception as e:
            # Create a minimal error report
            return GapReport(
                md_file=md_file,
                rosetta_file=rosetta_file,
                total_issues=0,
                critical_issues=0,
                high_issues=0,
                medium_issues=0,
                low_issues=0,
                issues=[],
                summary=f"Error during analysis: {str(e)}"
            ) 