# Back-compat shim: re-export from utils
from utils.bedrock_client import BedrockClient, BedrockError

__all__ = ["BedrockClient", "BedrockError"]
