from .base import AIProvider
from .simulated import SimulatedAIProvider

def create_provider(config):
    if config.ai_backend == "simulated": return SimulatedAIProvider()
    from .bedrock import BedrockProvider
    return BedrockProvider(config)
