import boto3
import json
from typing import Dict, Any, Optional
from configs.config import Config
import os
import logging
from langsmith import traceable

class BedrockClient:
    """Client for interacting with AWS Bedrock Claude model."""
    
    def __init__(self):
        """Initialize the Bedrock client and logger."""
        self.client = boto3.client(
            'bedrock-runtime',
            region_name=Config.AWS_REGION
        )
        self.model_id = Config.BEDROCK_MODEL_ID
        self.logger = logging.getLogger(__name__)
        if not self.logger.hasHandlers():
            logging.basicConfig(level=logging.INFO)
    
    @traceable(name="BedrockClient.invoke_model")
    def invoke_model(self, prompt: str, max_tokens: int = 4000, response_format: Optional[Dict[str, Any]] = None) -> str:
        """
        Invoke the Claude model with a prompt.
        
        Args:
            prompt: The prompt to send to the model
            max_tokens: Maximum number of tokens to generate
            response_format: Optional structured output format specification (not supported in current Bedrock version)
            
        Returns:
            The model's response as a string
        """
        self.logger.debug("invoke_model started")
        try:
            self.logger.debug("Creating request body")
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
            
            # Note: response_format is not supported in current Bedrock API version
            # We'll handle structured output through prompt engineering and parsing
            if response_format:
                self.logger.warning("response_format parameter is not supported in current Bedrock API version")
                
            self.logger.debug("Request body created")
            self.logger.info("About to call Bedrock API")
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )
            self.logger.info("Bedrock API call completed")
            self.logger.debug("Parsing response")
            response_body = json.loads(response['body'].read())
            self.logger.debug("Response body parsed")
            
            text_content = response_body['content'][0]['text']
            self.logger.info(f"Text content extracted, length: {len(text_content)}")
            
            if not text_content or text_content.strip() == "":
                raise Exception("Empty text content in response")
            
            return text_content
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            raise Exception(f"Invalid JSON response from Bedrock: {str(e)}")
        except KeyError as e:
            self.logger.error(f"Key error: {e}")
            raise Exception(f"Missing key in Bedrock response: {str(e)}")
        except Exception as e:
            self.logger.error(f"General exception: {e}")
            raise Exception(f"Error invoking Bedrock model: {str(e)}")
    
    def get_gap_analysis_schema(self) -> Dict[str, Any]:
        """
        Get the JSON schema for gap analysis structured output.
        
        Returns:
            JSON schema for structured gap analysis response
        """
        return {
            "type": "object",
            "properties": {
                "total_issues": {
                    "type": "integer",
                    "description": "Total number of issues found"
                },
                "critical_issues": {
                    "type": "integer",
                    "description": "Number of critical severity issues"
                },
                "high_issues": {
                    "type": "integer",
                    "description": "Number of high severity issues"
                },
                "medium_issues": {
                    "type": "integer",
                    "description": "Number of medium severity issues"
                },
                "low_issues": {
                    "type": "integer",
                    "description": "Number of low severity issues"
                },
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "issue_type": {
                                "type": "string",
                                "enum": ["missing", "divergent", "inconsistent", "structural"],
                                "description": "Type of issue found"
                            },
                            "description": {
                                "type": "string",
                                "description": "Clear description of the issue"
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                                "description": "Severity level of the issue"
                            },
                            "line_references": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "description": "List of line numbers or sections where the issue occurs"
                            },
                            "section": {
                                "type": "string",
                                "description": "The specific section or component affected"
                            },
                            "recommendation": {
                                "type": "string",
                                "description": "How to fix the issue"
                            }
                        },
                        "required": ["issue_type", "description", "severity", "line_references", "section", "recommendation"]
                    },
                    "description": "List of all issues found"
                },
                "summary": {
                    "type": "string",
                    "description": "Summary of the analysis"
                }
            },
            "required": ["total_issues", "critical_issues", "high_issues", "medium_issues", "low_issues", "issues", "summary"]
        }
    
    @traceable(name="BedrockClient.analyze_files")
    def analyze_files(self, md_content: str, rosetta_content: str) -> str:
        """
        Analyze the content of paired Markdown and Rosetta files.
        
        Args:
            md_content: Content of the Markdown file
            rosetta_content: Content of the Rosetta file
            
        Returns:
            JSON string with gap analysis results
        """
        self.logger.info("Starting analyze_files")
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', 'gap_analyst.prompt')
        self.logger.debug(f"Prompt path: {prompt_path}")
        with open(prompt_path, 'r') as f:
            prompt_template = f.read()
        self.logger.debug("Prompt template loaded")
        self.logger.debug(f"md_content length: {len(md_content)}")
        self.logger.debug(f"rosetta_content length: {len(rosetta_content)}")
        self.logger.debug(f"md_content preview: {repr(md_content[:100])}")
        self.logger.debug(f"rosetta_content preview: {repr(rosetta_content[:100])}")
        try:
            prompt = prompt_template.format(md_content=md_content, rosetta_content=rosetta_content)
            self.logger.info("Prompt formatted successfully")
        except Exception as e:
            self.logger.error(f"Error formatting prompt: {e}")
            raise
        
        # Since structured output is not supported in current Bedrock API version,
        # we'll use the traditional approach with improved parsing
        self.logger.info("About to call invoke_model")
        response = self.invoke_model(prompt)
        self.logger.info("invoke_model completed")
        self.logger.debug("\n--- RAW BEDROCK RESPONSE ---\n" + repr(response) + "\n--- END RAW BEDROCK RESPONSE ---\n")
        
        # Extract JSON from response
        extracted = self._extract_json_from_response(response)
        self.logger.info(f"JSON extracted: {repr(extracted)[:200]}")
        return extracted
    
    def _extract_json_from_response(self, response: str) -> str:
        """
        Extract JSON from the response, handling markdown code blocks and extra text.
        This is a fallback method when structured output fails.
        
        Args:
            response: Raw response from the model
        Returns:
            Clean JSON string
        """
        import re
        response = response.strip()
        
        # Remove markdown code block markers if present
        if response.startswith('```json'):
            response = response[7:]
        elif response.startswith('```'):
            response = response[3:]
        if response.endswith('```'):
            response = response[:-3]
        response = response.strip()
        
        # Try to extract the first JSON object using regex
        # Look for the most complete JSON object
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = list(re.finditer(json_pattern, response, re.DOTALL))
        
        if matches:
            # Find the longest match (most complete JSON)
            longest_match = max(matches, key=lambda m: len(m.group(0)))
            return longest_match.group(0)
        
        # Fallback: try to find any JSON-like structure
        # Look for opening and closing braces
        start = response.find('{')
        end = response.rfind('}')
        
        if start != -1 and end != -1 and end > start:
            return response[start:end+1]
        
        # Last resort: return the stripped response
        return response 