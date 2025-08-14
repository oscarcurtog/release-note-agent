#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
from typing import Dict, Any, Optional

import boto3
from configs.config import Config


class BedrockError(Exception):
    """Typed error with a lightweight `.code` used by the agent for guardrails."""
    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


class BedrockClient:
    """Client for interacting with AWS Bedrock Claude model."""

    def __init__(self) -> None:
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=Config.AWS_REGION,
        )
        self.model_id = Config.BEDROCK_MODEL_ID
        self.logger = logging.getLogger(__name__)
        if not self.logger.hasHandlers():
            logging.basicConfig(level=logging.INFO)

    def invoke_model(
        self,
        prompt: str,
        max_tokens: int = 4000,
        response_format: Optional[Dict[str, Any]] = None,  # kept for API compat
    ) -> str:
        """
        Invoke the Claude model with a prompt and return the raw text.
        """
        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                # Claude en Bedrock requiere lista de bloques en `content`
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": prompt}]}
                ],
                # opcional: "temperature": 0.1,
            }

            if response_format:
                self.logger.warning(
                    "response_format is not supported in current Bedrock API; ignoring."
                )

            resp = self.client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body).encode("utf-8"),
            )
            # cuerpo es un stream; lo leemos y parseamos
            payload = resp.get("body")
            raw = payload.read() if hasattr(payload, "read") else payload
            data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)

            # Respuesta Anthropic (Claude) en Bedrock:
            # { ..., "content": [{"type":"text","text":"..."}], ... }
            content = data["content"][0]["text"]
            if not content or not content.strip():
                raise BedrockError("Empty text content in response", code="UNKNOWN")
            return content

        except json.JSONDecodeError as e:
            raise BedrockError(f"Invalid JSON response from Bedrock: {e}", code="UNKNOWN")
        except KeyError as e:
            raise BedrockError(f"Missing key in Bedrock response: {e}", code="UNKNOWN")
        except Exception as e:
            raise BedrockError(f"Error invoking Bedrock model: {e}", code="UNKNOWN")

    def complete_json(self, prompt: str) -> str:
        """
        Back-compat shim expected by the agent: returns the raw text
        (which should contain JSON) using invoke_model.
        """
        try:
            return self.invoke_model(prompt, max_tokens=4000)
        except BedrockError:
            raise
        except Exception as e:
            # normalizamos a BedrockError para el agente
            raise BedrockError(f"Bedrock completion failed: {e}", code="UNKNOWN")

    def get_gap_analysis_schema(self) -> Dict[str, Any]:
        """JSON schema kept for compatibility with other tools."""
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
