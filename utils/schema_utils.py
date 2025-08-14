#!/usr/bin/env python3
from typing import Type
from pydantic import BaseModel


def to_json_schema(model_cls: Type[BaseModel]) -> dict:
	"""Return JSON Schema for a Pydantic v2 model class.

	Used to inject into LLM prompt in Step 6.
	"""
	return model_cls.model_json_schema()
