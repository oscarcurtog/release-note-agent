import os
import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langsmith import Client
from langsmith.run_helpers import traceable

# Load environment variables from .env file
load_dotenv()

from utils.bedrock_client import BedrockClient
from utils.structured_output import StructuredOutputClient, StructuredOutputError
from utils.data_models import GapReport, GapIssue, SeverityLevel
from configs.config import Config

class DocumenterState(BaseModel):
    """State for the documenter agent workflow."""
    gap_report: GapReport
    md_file: str = ""
    rosetta_file: str = ""
    md_content: str = ""
    rosetta_content: str = ""
    missing_sections: List[Dict[str, Any]] = []
    enhanced_content: str = ""
    generated_sections: List[Dict[str, Any]] = []
    error: str = ""

class MissingSection(BaseModel):
    """Model for missing section information."""
    section_name: str = Field(..., description="Name of the missing section")
    description: str = Field(..., description="Description of what should be in this section")
    severity: SeverityLevel = Field(..., description="Severity level of the missing section")
    source_reference: str = Field(..., description="Reference to source material in Rosetta file")
    content_outline: str = Field(..., description="Outline of what content should be included")

class GeneratedSection(BaseModel):
    """Model for generated section content."""
    section_name: str = Field(..., description="Name of the section")
    content: str = Field(..., description="Generated Markdown content")
    source_references: List[str] = Field(..., description="References to source material used")
    quality_score: float = Field(..., description="Quality score from 0-1")

class DocumenterAgent:
    """Agent for generating missing Markdown sections based on gap analysis."""
    
    def __init__(self):
        """Initialize the documenter agent."""
        self.bedrock_client = BedrockClient()
        self.structured_client = StructuredOutputClient(self.bedrock_client)
        self.langsmith_client = Client()
    

    
    @traceable(name="load_files")
    def _load_files(self, state: DocumenterState) -> DocumenterState:
        """Load the content of both files."""
        try:
            # Extract file names from gap report
            state.md_file = state.gap_report.md_file
            state.rosetta_file = state.gap_report.rosetta_file
            
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
        return DocumenterState(**state.model_dump())
    
    @traceable(name="analyze_missing_sections")
    def _analyze_missing_sections(self, state: DocumenterState) -> DocumenterState:
        """Analyze gap report to identify missing sections that need generation."""
        try:
            if state.error:
                return DocumenterState(**state.model_dump())
            
            # Filter issues that indicate missing sections
            missing_section_issues = [
                issue for issue in state.gap_report.issues
                if issue.issue_type in ["missing", "structural"] and issue.severity in [SeverityLevel.CRITICAL, SeverityLevel.HIGH]
            ]
            
            # Create missing section objects
            state.missing_sections = []
            for issue in missing_section_issues:
                missing_section = {
                    "section_name": issue.section,
                    "description": issue.description,
                    "severity": issue.severity,
                    "source_reference": ", ".join(issue.line_references),
                    "content_outline": issue.recommendation
                }
                state.missing_sections.append(missing_section)
            
        except Exception as e:
            state.error = f"Error analyzing missing sections: {str(e)}"
        
        # Ensure we return the state object, not a dict
        return DocumenterState(**state.model_dump())
    
    @traceable(name="generate_sections")
    def _generate_sections(self, state: DocumenterState) -> DocumenterState:
        """Generate missing Markdown sections using Bedrock."""
        try:
            if state.error or not state.missing_sections:
                return DocumenterState(**state.model_dump())
            
            # Load the documenter prompt template
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', 'documenter.prompt')
            with open(prompt_path, 'r') as f:
                prompt_template = f.read()
            
            state.generated_sections = []
            
            for missing_section in state.missing_sections:
                # Format the prompt for this specific section
                prompt = prompt_template.format(
                    section_name=missing_section["section_name"],
                    description=missing_section["description"],
                    source_reference=missing_section["source_reference"],
                    content_outline=missing_section["content_outline"],
                    rosetta_content=state.rosetta_content,
                    existing_md_content=state.md_content
                )
                
                # Generate content using structured output
                try:
                    generated_section = self.structured_client.create_with_fallback(
                        model_class=GeneratedSection,
                        prompt=prompt,
                        max_tokens=4000
                    )
                    
                    state.generated_sections.append({
                        "section_name": generated_section.section_name,
                        "content": generated_section.content,
                        "source_references": generated_section.source_references,
                        "quality_score": generated_section.quality_score
                    })
                    
                except StructuredOutputError as e:
                    # Fallback to simple text generation
                    response = self.bedrock_client.invoke_model(prompt, max_tokens=4000)
                    state.generated_sections.append({
                        "section_name": missing_section["section_name"],
                        "content": response,
                        "source_references": [missing_section["source_reference"]],
                        "quality_score": 0.7  # Default quality score for fallback
                    })
            
        except Exception as e:
            state.error = f"Error generating sections: {str(e)}"
        
        # Ensure we return the state object, not a dict
        return DocumenterState(**state.model_dump())
    
    @traceable(name="enhance_existing_content")
    def _enhance_existing_content(self, state: DocumenterState) -> DocumenterState:
        """Enhance existing Markdown content based on gap analysis."""
        try:
            if state.error:
                return DocumenterState(**state.model_dump())
            
            # Start with existing content
            enhanced_content = state.md_content
            
            # Add generated sections
            for section in state.generated_sections:
                section_markdown = f"\n\n## {section['section_name']}\n\n{section['content']}\n"
                enhanced_content += section_markdown
            
            state.enhanced_content = enhanced_content
            
        except Exception as e:
            state.error = f"Error enhancing content: {str(e)}"
        
        # Ensure we return the state object, not a dict
        return DocumenterState(**state.model_dump())
    
    @traceable(name="validate_output")
    def _validate_output(self, state: DocumenterState) -> DocumenterState:
        """Validate the generated content and ensure it meets quality standards."""
        try:
            if state.error:
                return DocumenterState(**state.model_dump())
            
            # Basic validation checks
            if not state.enhanced_content:
                state.error = "No enhanced content generated"
                return DocumenterState(**state.model_dump())
            
            # Check if all critical missing sections were addressed
            critical_sections = [s for s in state.missing_sections if s["severity"] == SeverityLevel.CRITICAL]
            generated_critical = [s for s in state.generated_sections if s["quality_score"] >= 0.8]
            
            if len(critical_sections) > len(generated_critical):
                state.error = f"Not all critical sections were generated with sufficient quality. Expected: {len(critical_sections)}, Generated: {len(generated_critical)}"
            
        except Exception as e:
            state.error = f"Error validating output: {str(e)}"
        
        # Ensure we return the state object, not a dict
        return DocumenterState(**state.model_dump())
    
    def generate_documentation(self, gap_report: GapReport, output_file: str = None) -> Dict[str, Any]:
        """
        Generate missing Markdown sections based on gap analysis.
        
        Args:
            gap_report: GapReport object from the comparison agent
            output_file: Optional path to save the enhanced Markdown file
            
        Returns:
            Dictionary containing enhanced content and metadata
        """
        # Initialize state
        state = DocumenterState(gap_report=gap_report)
        
        # Run the workflow steps manually
        try:
            # Step 1: Load files
            state = self._load_files(state)
            if state.error:
                return {
                    "success": False,
                    "error": state.error,
                    "enhanced_content": None,
                    "generated_sections": [],
                    "missing_sections": [],
                    "output_file": None
                }
            
            # Step 2: Analyze missing sections
            state = self._analyze_missing_sections(state)
            if state.error:
                return {
                    "success": False,
                    "error": state.error,
                    "enhanced_content": None,
                    "generated_sections": [],
                    "missing_sections": state.missing_sections,
                    "output_file": None
                }
            
            # Step 3: Generate sections
            state = self._generate_sections(state)
            if state.error:
                return {
                    "success": False,
                    "error": state.error,
                    "enhanced_content": None,
                    "generated_sections": state.generated_sections,
                    "missing_sections": state.missing_sections,
                    "output_file": None
                }
            
            # Step 4: Enhance existing content
            state = self._enhance_existing_content(state)
            if state.error:
                return {
                    "success": False,
                    "error": state.error,
                    "enhanced_content": state.enhanced_content,
                    "generated_sections": state.generated_sections,
                    "missing_sections": state.missing_sections,
                    "output_file": None
                }
            
            # Step 5: Validate output
            state = self._validate_output(state)
            if state.error:
                return {
                    "success": False,
                    "error": state.error,
                    "enhanced_content": state.enhanced_content,
                    "generated_sections": state.generated_sections,
                    "missing_sections": state.missing_sections,
                    "output_file": None
                }
            
            # Save to file if output_file is specified
            saved_file_path = None
            if output_file and state.enhanced_content:
                try:
                    # Ensure the directory exists
                    os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
                    
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(state.enhanced_content)
                    saved_file_path = output_file
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to save output file: {str(e)}",
                        "enhanced_content": state.enhanced_content,
                        "generated_sections": state.generated_sections,
                        "missing_sections": state.missing_sections,
                        "output_file": None
                    }
            
            return {
                "success": True,
                "error": None,
                "enhanced_content": state.enhanced_content,
                "generated_sections": state.generated_sections,
                "missing_sections": state.missing_sections,
                "original_gap_report": gap_report.model_dump(),
                "output_file": saved_file_path
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Workflow execution failed: {str(e)}",
                "enhanced_content": None,
                "generated_sections": [],
                "missing_sections": [],
                "output_file": None
            }
