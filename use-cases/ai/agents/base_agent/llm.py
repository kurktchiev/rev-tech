import os

from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


def get_llm(provider_env="LLM_PROVIDER"):
    provider = os.environ.get(provider_env, "anthropic")
    if provider == "ollama":
        return ChatOllama(
            model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
        )
    if provider == "openai":
        return ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        )
    return ChatAnthropic(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
