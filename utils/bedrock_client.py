#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import logging
from typing import Dict, Any, Optional

import boto3
from configs.config import Config
from langsmith import traceable


class BedrockError(Exception):
    """Typed error with a lightweight `.code` used by the agent for guardrails."""
    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


class BedrockClient:
    """Client for interacting with AWS Bedrock Claude model."""

    def __init__(self) -> None:
        """Initialize the Bedrock client and logger."""
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=Config.AWS_REGION,
        )
        self.model_id = Config.BEDROCK_MODEL_ID
        self.logger = logging.getLogger(__name__)
        if not self.logger.hasHandlers():
            logging.basicConfig(level=logging.INFO)

    @traceable(name="BedrockClient.invoke_model")
    def invoke_model(
        self,
        prompt: str,
        max_tokens: int = 4000,
        response_format: Optional[Dict[str, Any]] = None,  # not used; kept for API compat
    ) -> str:
        """
        Invoke the Claude model with a prompt.

        Returns:
            The model's response text.
        """
        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            }

            if response_format:
                # Not supported today by Bedrock Converse payload; keep warning only.
                self.logger.warning(
                    "response_format is not supported in current Bedrock API version; ignoring."
                )

            resp = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
            )
            # Bedrock returns a streaming body object
            payload = resp.get("body")
            text = payload.read() if hasattr(payload, "read") else payload  # bytes or str
            data = json.loads(text.decode("utf-8") if isinstance(text, (bytes, bytearray)) else text)

            content = data["content"][0]["text"]
            if not content or not content.strip():
                raise BedrockError("Empty text content in response", code="UNKNOWN")
            return content

        except json.JSONDecodeError as e:
            raise BedrockError(f"Invalid JSON response from Bedrock: {e}", code="UNKNOWN")
        except KeyError as e:
            raise BedrockError(f"Missing key in Bedrock response: {e}", code="UNKNOWN")
        except Exception as e:
            # Leave as UNKNOWN; upstream maps codes for retries/feedback when needed.
            raise BedrockError(f"Error invoking Bedrock model: {e}", code="UNKNOWN")

    def get_gap_analysis_schema(self) -> Dict[str, Any]:
        """JSON schema for gap analysis structured output (kept for compatibility)."""
        return {
            "type": "object",
            "properties": {
                "total_issues": {"type": "integer"},
                "critical_issues": {"type": "integer"},
                "high_issues": {"type": "integer"},
                "medium_issues": {"type": "integer"},
                "low_issues": {"type": "integer"},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "issue_type": {"type": "string", "enum": ["missing", "divergent", "inconsistent", "structural"]},
                            "description": {"type": "string"},
                            "severity": {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                            "line_references": {"type": "array", "items": {"type": "string"}},
                            "section": {"type": "string"},
                            "recommendation": {"type": "string"},
                        },
                        "required": ["issue_type", "description", "severity", "line_references", "section", "recommendation"],
                    },
                },
                "summary": {"type": "string"},
            },
            "required": ["total_issues", "critical_issues", "high_issues", "medium_issues", "low_issues", "issues", "summary"],
        }

    @traceable(name="BedrockClient.analyze_files")
    def analyze_files(self, md_content: str, rosetta_content: str) -> str:
        """Analyze paired Markdown/Rosetta contents and return extracted JSON as string."""
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "gap_analyst.prompt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        prompt = prompt_template.format(md_content=md_content, rosetta_content=rosetta_content)

        response = self.invoke_model(prompt)
        extracted = self._extract_json_from_response(response)
        return extracted

    def _extract_json_from_response(self, response: str) -> str:
        """Extract JSON from a possibly mixed Markdown/text response."""
        import re

        s = response.strip()
        if s.startswith("```json"):
            s = s[7:]
        elif s.startswith("```"):
            s = s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()

        json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        matches = list(re.finditer(json_pattern, s, re.DOTALL))
        if matches:
            longest = max(matches, key=lambda m: len(m.group(0)))
            return longest.group(0)

        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return s[start : end + 1]
        return s


__all__ = ["BedrockClient", "BedrockError"]
#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import logging
from typing import Dict, Any, Optional

import boto3
from configs.config import Config
from langsmith import traceable


class BedrockError(Exception):
    """Typed error with a lightweight `.code` used by the agent for guardrails."""
    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


class BedrockClient:
    """Client for interacting with AWS Bedrock Claude model."""

    def __init__(self) -> None:
        """Initialize the Bedrock client and logger."""
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=Config.AWS_REGION,
        )
        self.model_id = Config.BEDROCK_MODEL_ID
        self.logger = logging.getLogger(__name__)
        if not self.logger.hasHandlers():
            logging.basicConfig(level=logging.INFO)

    @traceable(name="BedrockClient.invoke_model")
    def invoke_model(
        self,
        prompt: str,
        max_tokens: int = 4000,
        response_format: Optional[Dict[str, Any]] = None,  # not used; kept for API compat
    ) -> str:
        """
        Invoke the Claude model with a prompt.

        Returns:
            The model's response text.
        """
        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            }

            if response_format:
                # Not supported today by Bedrock Converse payload; keep warning only.
                self.logger.warning(
                    "response_format is not supported in current Bedrock API version; ignoring."
                )

            resp = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
            )
            # Bedrock returns a streaming body object
            payload = resp.get("body")
            text = payload.read() if hasattr(payload, "read") else payload  # bytes or str
            data = json.loads(text.decode("utf-8") if isinstance(text, (bytes, bytearray)) else text)

            content = data["content"][0]["text"]
            if not content or not content.strip():
                raise BedrockError("Empty text content in response", code="UNKNOWN")
            return content

        except json.JSONDecodeError as e:
            raise BedrockError(f"Invalid JSON response from Bedrock: {e}", code="UNKNOWN")
        except KeyError as e:
            raise BedrockError(f"Missing key in Bedrock response: {e}", code="UNKNOWN")
        except Exception as e:
            # Leave as UNKNOWN; upstream maps codes for retries/feedback when needed.
            raise BedrockError(f"Error invoking Bedrock model: {e}", code="UNKNOWN")

    def get_gap_analysis_schema(self) -> Dict[str, Any]:
        """JSON schema for gap analysis structured output (kept for compatibility)."""
        return {
            "type": "object",
            "properties": {
                "total_issues": {"type": "integer"},
                "critical_issues": {"type": "integer"},
                "high_issues": {"type": "integer"},
                "medium_issues": {"type": "integer"},
                "low_issues": {"type": "integer"},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "issue_type": {"type": "string", "enum": ["missing", "divergent", "inconsistent", "structural"]},
                            "description": {"type": "string"},
                            "severity": {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                            "line_references": {"type": "array", "items": {"type": "string"}},
                            "section": {"type": "string"},
                            "recommendation": {"type": "string"},
                        },
                        "required": ["issue_type", "description", "severity", "line_references", "section", "recommendation"],
                    },
                },
                "summary": {"type": "string"},
            },
            "required": ["total_issues", "critical_issues", "high_issues", "medium_issues", "low_issues", "issues", "summary"],
        }

    @traceable(name="BedrockClient.analyze_files")
    def analyze_files(self, md_content: str, rosetta_content: str) -> str:
        """Analyze paired Markdown/Rosetta contents and return extracted JSON as string."""
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "gap_analyst.prompt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        prompt = prompt_template.format(md_content=md_content, rosetta_content=rosetta_content)

        response = self.invoke_model(prompt)
        extracted = self._extract_json_from_response(response)
        return extracted

    def _extract_json_from_response(self, response: str) -> str:
        """Extract JSON from a possibly mixed Markdown/text response."""
        import re

        s = response.strip()
        if s.startswith("```json"):
            s = s[7:]
        elif s.startswith("```"):
            s = s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()

        json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        matches = list(re.finditer(json_pattern, s, re.DOTALL))
        if matches:
            longest = max(matches, key=lambda m: len(m.group(0)))
            return longest.group(0)

        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return s[start : end + 1]
        return s


__all__ = ["BedrockClient", "BedrockError"]
