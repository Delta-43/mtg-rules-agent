import logging

from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from core_config import Config

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    """Raised when the selected LLM_PROVIDER is missing required configuration."""


def build_chat_model():
    """Construct the chat model for the configured provider.

    Config.LLM_PROVIDER selects between a local Ollama model and a hosted model
    via OpenRouter (OpenAI-API-compatible), so the same agent code runs whether or
    not the deployment has access to local GPU/CPU inference.
    """
    if Config.LLM_PROVIDER == "hosted":
        if not Config.OPENROUTER_API_KEY:
            raise LLMConfigError(
                "LLM_PROVIDER=hosted but OPENROUTER_API_KEY is not set."
            )
        return ChatOpenAI(
            base_url=Config.OPENROUTER_BASE_URL,
            api_key=Config.OPENROUTER_API_KEY,
            model=Config.OPENROUTER_MODEL,
            temperature=0.1,
        )

    if Config.LLM_MODEL.endswith(":cloud"):
        # LLM_PROVIDER=local only means "talks to your own Ollama instance" --
        # it does NOT mean fully offline/air-gapped. A ":cloud" tag routes
        # inference to Ollama's own infrastructure (requires internet + a
        # one-time `ollama signin`); the client here just proxies to it. Log
        # this at startup rather than leaving it to be discovered from a
        # confusing 401 at first inference, or from someone assuming
        # LLM_PROVIDER=local was a guarantee of no network dependency.
        logger.warning(
            "LLM_MODEL=%s is an Ollama cloud model: inference runs on "
            "Ollama's infrastructure, not this host, despite LLM_PROVIDER=local. "
            "Requires internet access and a one-time 'ollama signin'. For a "
            "genuinely offline/local model, set LLM_MODEL to a local weights tag.",
            Config.LLM_MODEL,
        )

    return ChatOllama(
        model=Config.LLM_MODEL,
        base_url=Config.OLLAMA_BASE_URL,
        temperature=0.1,
        reasoning=Config.LLM_REASONING,
        num_predict=Config.LLM_NUM_PREDICT,
        num_ctx=Config.LLM_NUM_CTX,
        # Ollama's own default (1.1) is a weak penalty; raised a bit as one
        # layer of defense against the model degenerating into repeating the
        # same text until num_predict cuts it off (see agent.py's
        # _truncate_repetition -- the deterministic backstop for when this
        # doesn't fully prevent it, e.g. against an Ollama-cloud model whose
        # own generation settings this may not reach).
        repeat_penalty=1.3,
    )
