"""
Structured Output utilities for AWS Bedrock.

This module provides utilities for getting structured output from AWS Bedrock models,
similar to OpenAI's structured outputs feature.

Note: AWS Bedrock currently doesn't support the response_format parameter in the API,
so we use prompt engineering and robust parsing to achieve structured output.
"""

import json
import logging
from typing import Dict, Any, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError
from utils.bedrock_client import BedrockClient

T = TypeVar('T', bound=BaseModel)

class StructuredOutputError(Exception):
    """Exception raised when structured output fails."""
    pass

class StructuredOutputClient:
    """
    Client for getting structured output from AWS Bedrock models.
    
    This provides a clean interface similar to OpenAI's structured outputs,
    allowing you to specify Pydantic models and get validated responses.
    
    Note: Since AWS Bedrock doesn't currently support response_format,
    we use prompt engineering and robust parsing to achieve structured output.
    """
    
    def __init__(self, bedrock_client: Optional[BedrockClient] = None):
        """
        Initialize the structured output client.
        
        Args:
            bedrock_client: Optional BedrockClient instance. If not provided, creates a new one.
        """
        self.bedrock_client = bedrock_client or BedrockClient()
        self.logger = logging.getLogger(__name__)
    
    def create(self, 
               model_class: Type[T], 
               prompt: str, 
               max_tokens: int = 4000,
               **kwargs) -> T:
        """
        Create a structured output using a Pydantic model.
        
        Args:
            model_class: The Pydantic model class to validate against
            prompt: The prompt to send to the model
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional arguments to pass to the model
            
        Returns:
            An instance of the specified Pydantic model
            
        Raises:
            StructuredOutputError: If the response cannot be parsed or validated
        """
        try:
            # Generate JSON schema from Pydantic model
            schema = self._pydantic_to_json_schema(model_class)
            
            # Enhance the prompt with schema information
            enhanced_prompt = self._enhance_prompt_with_schema(prompt, schema)
            
            # Call the model (without response_format since it's not supported)
            response = self.bedrock_client.invoke_model(
                prompt=enhanced_prompt,
                max_tokens=max_tokens,
                **kwargs
            )
            
            # Parse the JSON response
            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                # Try to extract JSON from the response
                extracted_json = self.bedrock_client._extract_json_from_response(response)
                try:
                    data = json.loads(extracted_json)
                except json.JSONDecodeError as e2:
                    raise StructuredOutputError(f"Invalid JSON response: {e2}. Raw response: {response[:200]}...")
            
            # Validate against Pydantic model
            try:
                return model_class(**data)
            except ValidationError as e:
                raise StructuredOutputError(f"Validation error: {e}")
                
        except Exception as e:
            if isinstance(e, StructuredOutputError):
                raise
            raise StructuredOutputError(f"Structured output failed: {e}")
    
    def _enhance_prompt_with_schema(self, prompt: str, schema: Dict[str, Any]) -> str:
        """
        Enhance the prompt with schema information to guide the model's response.
        
        Args:
            prompt: Original prompt
            schema: JSON schema for the expected response
            
        Returns:
            Enhanced prompt with schema guidance
        """
        schema_guidance = f"""
Please respond with a valid JSON object that matches this schema:

{json.dumps(schema, indent=2)}

Important:
- Ensure all required fields are present
- Use the exact field names from the schema
- For enum fields, use only the allowed values
- For arrays, provide a list of objects with the correct structure
- Do not include any text before or after the JSON object

Your response should be a single, valid JSON object.
"""
        
        return f"{prompt}\n\n{schema_guidance}"
    
    def _pydantic_to_json_schema(self, model_class: Type[BaseModel]) -> Dict[str, Any]:
        """
        Convert a Pydantic model to JSON schema.
        
        Args:
            model_class: The Pydantic model class
            
        Returns:
            JSON schema dictionary
        """
        return model_class.model_json_schema()
    
    def create_with_fallback(self,
                           model_class: Type[T],
                           prompt: str,
                           max_tokens: int = 4000,
                           **kwargs) -> T:
        """
        Create structured output with enhanced fallback parsing.
        
        This method tries structured output first, and if it fails,
        falls back to manual JSON extraction and validation.
        
        Args:
            model_class: The Pydantic model class to validate against
            prompt: The prompt to send to the model
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional arguments to pass to the model
            
        Returns:
            An instance of the specified Pydantic model
        """
        try:
            # Try structured output first
            return self.create(model_class, prompt, max_tokens, **kwargs)
        except StructuredOutputError as e:
            self.logger.warning(f"Structured output failed, trying fallback: {e}")
            
            # Fallback: use regular model call and extract JSON
            try:
                response = self.bedrock_client.invoke_model(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    **kwargs
                )
                
                # Extract JSON from response
                extracted_json = self.bedrock_client._extract_json_from_response(response)
                
                # Parse and validate
                data = json.loads(extracted_json)
                return model_class(**data)
                
            except Exception as fallback_error:
                raise StructuredOutputError(
                    f"Both structured output and fallback failed. "
                    f"Structured error: {e}. Fallback error: {fallback_error}"
                )

# Convenience function for easy usage
def create_structured_output(model_class: Type[T], 
                           prompt: str, 
                           max_tokens: int = 4000,
                           use_fallback: bool = False,
                           **kwargs) -> T:
    """
    Convenience function for creating structured output.
    
    Args:
        model_class: The Pydantic model class to validate against
        prompt: The prompt to send to the model
        max_tokens: Maximum number of tokens to generate
        use_fallback: Whether to use fallback parsing if structured output fails
        **kwargs: Additional arguments to pass to the model
        
    Returns:
        An instance of the specified Pydantic model
    """
    client = StructuredOutputClient()
    
    if use_fallback:
        return client.create_with_fallback(model_class, prompt, max_tokens, **kwargs)
    else:
        return client.create(model_class, prompt, max_tokens, **kwargs)
