"""The LLM path: an async Gemini wrapper, structured output schemas and the Gemini-backed agents.

Everything here is optional. With no API key (or LLM_MODE=offline) `enabled()` is False and every
caller uses the deterministic code path instead; with a key, any LLM failure also falls back to it.
"""

from vik.config import get_settings


def enabled() -> bool:
    s = get_settings()
    if s.llm_mode == "offline":
        return False
    return bool(s.gemini_key())
