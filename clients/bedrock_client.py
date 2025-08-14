#!/usr/bin/env python3
from __future__ import annotations

import math
import random
import time
from typing import Optional

import boto3
from botocore.exceptions import ReadTimeoutError, EndpointConnectionError, ClientError

from configs.config import Config


class BedrockError(Exception):
	def __init__(self, message: str, code: str = "UNKNOWN") -> None:
		super().__init__(message)
		self.code = code


class BedrockClient:
	def __init__(self, model_id: Optional[str] = None, timeout_s: Optional[int] = None, max_output_tokens: int = 2000) -> None:
		cfg = Config.get_bedrock_config()
		self.region = cfg.get("region_name", Config.AWS_REGION)
		self.model_id = model_id or cfg.get("model_id", Config.BEDROCK_MODEL_ID)
		self.timeout_s = int(timeout_s if timeout_s is not None else Config.HTTP_TIMEOUT_S)
		self.max_output_tokens = int(max_output_tokens)
		self._runtime = boto3.client("bedrock-runtime", region_name=self.region)
		self.temperature = 0.1
		self._tokens_per_char = float(Config.DIFF_TOKENS_PER_CHAR)
		self._hard_total_cap = 100000  # combined prompt+response tokens
		self._global_cap_s = 300

	def _estimate_tokens(self, text: str) -> int:
		if not text:
			return 0
		return math.ceil(len(text) / max(1.0, self._tokens_per_char))

	def _invoke(self, prompt: str) -> str:
		# Claude 3 Sonnet on Bedrock (Converse-style payload)
		# Use text generation; enforce low temperature
		body = {
			"anthropic_version": "bedrock-2023-05-31",
			"max_tokens": self.max_output_tokens,
			"temperature": self.temperature,
			"messages": [
				{"role": "user", "content": [{"type": "text", "text": prompt}]}
			],
		}
		response = self._runtime.invoke_model(
			modelId=self.model_id,
			contentType="application/json",
			accept="application/json",
			body=bytes(str(body), "utf-8"),
		)
		payload = response.get("body")
		if hasattr(payload, "read"):
			payload_text = payload.read().decode("utf-8", errors="ignore")
		else:
			payload_text = str(payload)
		return payload_text

	def complete_json(self, prompt: str) -> str:
		start = time.monotonic()
		# Budget guardrails
		tokens_est = self._estimate_tokens(prompt) + self.max_output_tokens
		if tokens_est > self._hard_total_cap:
			raise BedrockError("Prompt exceeds hard token cap", code="UNKNOWN")
		# Retries on transient errors
		exc: Optional[Exception] = None
		for attempt in range(3):
			try:
				if (time.monotonic() - start) >= self._global_cap_s:
					raise BedrockError("Global timeout exceeded", code="TIMEOUT")
				return self._invoke(prompt)
			except BedrockError:
				# Propagate our typed errors without remapping
				raise
			except ReadTimeoutError as e:
				exc = e
				code = "TIMEOUT"
			except EndpointConnectionError as e:
				exc = e
				code = "NETWORK"
			except ClientError as e:
				exc = e
				err = e.response.get("Error", {}) if hasattr(e, "response") else {}
				status = err.get("Code", "") or err.get("StatusCode", "")
				msg = err.get("Message", "")
				low = (str(status) + " " + str(msg)).lower()
				if "throttl" in low or "429" in low or "rate" in low:
					code = "RATE_LIMIT"
				elif "unauthorized" in low or "403" in low or "401" in low:
					code = "UNAUTHORIZED"
				else:
					code = "UNKNOWN"
			except Exception as e:
				exc = e
				code = "UNKNOWN"
			# backoff if transient
			if code in ("TIMEOUT", "NETWORK", "RATE_LIMIT") and attempt < 2:
				backoff = (2 ** attempt) + random.random()
				time.sleep(min(backoff, 2.5))
				continue
			raise BedrockError(f"Bedrock error: {exc}", code=code)
		raise BedrockError("Unknown failure", code="UNKNOWN")
