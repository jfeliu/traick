import openai
from traick.config import settings

_client: openai.AsyncOpenAI | None = None


def get_client() -> openai.AsyncOpenAI:
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key=settings.ollama_api_key,
        )
    return _client
