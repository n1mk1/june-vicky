"""Async Anthropic wrapper: one place for model choice, effort, fallbacks, refusals, errors and spend.

- Each route names a model tier and an effort (TRD §5.2); thinking stays adaptive (it can't be turned
  off on the 5.5 models) except the latency-bound chair, which uses `between_tools` on Sonnet 5.5.
- Structured outputs go through `messages.parse()`; tool loops through the SDK tool runner.
- `stop_reason` is checked before any content is read: `refusal` → `LLMRefusal`, `max_tokens` →
  `LLMError`. Opus/Sonnet requests opt into server-side fallbacks (`fallbacks: "default"`).
- Every response's usage is priced at list rates and added to `vicky:spend:{date}`; once the day's
  budget is spent, calls raise `BudgetExceeded` (and `auth.require_budget` turns LLM routes into 402).

Callers treat every `LLMError` the same way: use the deterministic path instead.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import anthropic
import pydantic
from anthropic import AsyncAnthropic

from vicky import kv
from vicky.config import get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=pydantic.BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """Any failure on the LLM path; callers fall back to the deterministic code path."""


class LLMRefusal(LLMError):
    def __init__(self, category: str | None, explanation: str | None = None):
        super().__init__(f"model declined ({category or 'unspecified'})")
        self.category = category
        self.explanation = explanation


class LLMUnavailable(LLMError):
    """Network, rate limit, timeout or server error."""


class BudgetExceeded(LLMError):
    pass


@dataclass(frozen=True)
class Route:
    tier: Literal["deep", "fast", "tiny"]
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    max_tokens: int
    thinking_off: bool = False  # Sonnet 5.5 only: `between_tools` (no thinking) for sub-second routes


# TRD §5.2 roster.
ROUTES: dict[str, Route] = {
    "memo": Route("deep", "high", 16000),
    "update_bid": Route("fast", "low", 4000),
    "speak": Route("fast", "medium", 4000),
    "chair": Route("fast", "low", 1024, thinking_off=True),
    "judge": Route("deep", "high", 8000),       # Vicky scores the answer
    "review": Route("tiny", "low", 2000),       # Vicky reviews an investor's draft line before it is spoken
    "probes": Route("fast", "medium", 6000),    # knowledge questions from the founder's notes, at session start
    "ask_knowledge": Route("fast", "low", 2000),
    "verify": Route("tiny", "low", 2000),       # Vicky checks a knowledge answer against the notes
    "claims": Route("tiny", "low", 4000),
    "mapper": Route("fast", "medium", 8000),
    "doc_facts": Route("deep", "medium", 16000),
    "doc_parse": Route("deep", "medium", 16000),
    "qa": Route("fast", "medium", 3000),
    "qa_rag": Route("tiny", "low", 3000),     # Ask Vicky from retrieved chunks (docs/08-RAG.md)
    "qa_full": Route("tiny", "medium", 4000),  # the catch-all over the whole vault, only after the user accepts
    "persona": Route("fast", "medium", 8000),
    "kb_organize": Route("fast", "medium", 16000),
    "kb_hubs": Route("fast", "medium", 12000),
    "kb_profile": Route("fast", "medium", 6000),
}

# USD per million tokens: input, output, cache read, cache write (5-minute TTL). List prices.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-8": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5),
}
UNKNOWN_PRICE = (5.0, 25.0, 0.50, 6.25)  # an unlisted (fallback) model is priced at the dearest rate


def price_of(model: str) -> tuple[float, float, float, float]:
    for name in sorted(PRICES, key=len, reverse=True):
        if model == name or model.startswith(name + "-"):
            return PRICES[name]
    return UNKNOWN_PRICE


def usage_usd(model: str, usage: Any) -> float:
    if usage is None:
        return 0.0
    p_in, p_out, p_read, p_write = price_of(model)
    n_in = getattr(usage, "input_tokens", 0) or 0
    n_out = getattr(usage, "output_tokens", 0) or 0
    n_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    n_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (n_in * p_in + n_out * p_out + n_read * p_read + n_write * p_write) / 1e6


async def spent_today() -> float:
    try:
        return await kv.spend_today()
    except Exception:  # Redis down: the budget can't be read, so it can't block
        return 0.0


async def over_budget() -> bool:
    return await spent_today() >= get_settings().daily_usd_budget


def model_for(route: Route) -> str:
    s = get_settings()
    return {"deep": s.model_deep, "fast": s.model_fast, "tiny": s.model_tiny}[route.tier]


def supports_fallbacks(model: str) -> bool:
    # Server-side fallbacks exist for Opus 5.x and Sonnet 5.5 (not Haiku 5.5).
    return model.startswith("claude-opus-5") or model.startswith("claude-sonnet-5-5")


def system_blocks(system: str | list[str]) -> list[dict]:
    """Stable → volatile segments, each ending in a cache breakpoint (max two: rules, persona)."""
    parts = [system] if isinstance(system, str) else [p for p in system if p]
    blocks: list[dict] = [{"type": "text", "text": p} for p in parts]
    for b in blocks[-2:]:
        b["cache_control"] = {"type": "ephemeral"}
    return blocks


class LLM:
    def __init__(self, client: AsyncAnthropic | None = None):
        s = get_settings()
        self.client = client or AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=2)
        self.spent = 0.0  # this process, for logs and tests

    # ------------------------------------------------------------ plumbing

    def params(self, route_name: str, system: str | list[str], messages: list[dict]) -> dict[str, Any]:
        route = ROUTES[route_name]
        model = model_for(route)
        p: dict[str, Any] = {"model": model, "max_tokens": route.max_tokens, "system": system_blocks(system),
                             "messages": messages, "output_config": {"effort": route.effort}}
        if route.thinking_off and model.startswith("claude-sonnet-5-5"):
            p["thinking"] = {"type": "between_tools"}
        if get_settings().llm_server_fallbacks and supports_fallbacks(model):
            p["betas"] = [FALLBACK_BETA]
            p["fallbacks"] = "default"
        return p

    async def _record(self, msg: Any) -> None:
        usd = usage_usd(getattr(msg, "model", ""), getattr(msg, "usage", None))
        self.spent += usd
        if usd <= 0:
            return
        try:
            await kv.add_spend(usd)
        except Exception as e:  # spend tracking must never break a turn
            log.warning("could not record LLM spend: %s", e)

    async def _settle(self, msg: Any) -> Any:
        """Record spend, then check why the model stopped before anyone reads the content."""
        await self._record(msg)
        reason = getattr(msg, "stop_reason", None)
        if reason == "refusal":
            d = getattr(msg, "stop_details", None)
            raise LLMRefusal(getattr(d, "category", None), getattr(d, "explanation", None))
        if reason == "max_tokens":
            raise LLMError("response hit max_tokens")
        if reason == "pause_turn":
            raise LLMError("turn paused before finishing")
        return msg

    async def _guard(self, call: Callable[[], Awaitable[Any]]) -> Any:
        if await over_budget():
            raise BudgetExceeded("daily LLM budget reached")
        try:
            return await call()
        except pydantic.ValidationError as e:
            raise LLMError(f"structured output did not validate: {e.errors()[:1]}") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"bad request: {e.message}") from e
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise LLMUnavailable(f"credentials rejected ({e.status_code})") from e
        except anthropic.RateLimitError as e:
            raise LLMUnavailable("rate limited") from e
        except anthropic.APIStatusError as e:
            raise LLMUnavailable(f"API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:  # includes APITimeoutError
            raise LLMUnavailable(f"connection: {e}") from e
        except TimeoutError as e:
            raise LLMUnavailable("timed out") from e

    def _client(self, timeout: float | None):
        return self.client.with_options(timeout=timeout, max_retries=0) if timeout else self.client

    # ------------------------------------------------------------ calls

    async def parse(self, route: str, schema: type[T], *, system: str | list[str], messages: list[dict],
                    request_timeout_s: float | None = None) -> T:
        """One structured-output call; returns the validated `schema` instance."""
        p = self.params(route, system, messages)

        async def call() -> T:
            msg = await self._client(request_timeout_s).beta.messages.parse(output_format=schema, **p)
            await self._settle(msg)
            out = msg.parsed_output
            if out is None:
                raise LLMError("no structured output in the response")
            return out

        return await self._guard(call)

    async def text(self, route: str, *, system: str | list[str], messages: list[dict],
                   request_timeout_s: float | None = None) -> str:
        msg = await self.message(route, system=system, messages=messages, request_timeout_s=request_timeout_s)
        return "".join(b.text for b in msg.content if b.type == "text").strip()

    async def message(self, route: str, *, system: str | list[str], messages: list[dict],
                      request_timeout_s: float | None = None) -> Any:
        """A plain call that returns the whole message (used for citations, which can't be combined
        with structured outputs)."""
        p = self.params(route, system, messages)

        async def call() -> Any:
            return await self._settle(await self._client(request_timeout_s).beta.messages.create(**p))

        return await self._guard(call)

    async def run_tools(self, route: str, schema: type[T], *, system: str | list[str], messages: list[dict],
                        tools: Iterable[Any], max_iterations: int = 6) -> T:
        """Tool runner over read-only tools, ending in a structured `schema` answer."""
        p = self.params(route, system, messages)

        async def call() -> T:
            runner = self.client.beta.messages.tool_runner(tools=list(tools), output_format=schema,
                                                            max_iterations=max_iterations, **p)
            last = None
            async for msg in runner:
                last = msg
                await self._record(msg)
                if msg.stop_reason == "refusal":
                    d = getattr(msg, "stop_details", None)
                    raise LLMRefusal(getattr(d, "category", None), getattr(d, "explanation", None))
            if last is None:
                raise LLMError("tool runner returned nothing")
            if last.stop_reason != "end_turn":
                raise LLMError(f"tool loop ended on {last.stop_reason}")
            if last.parsed_output is None:
                raise LLMError("no structured output after the tool loop")
            return last.parsed_output

        return await self._guard(call)

    async def upload(self, filename: str, data: bytes, mime: str) -> str:
        async def call() -> str:
            meta = await self.client.files.upload(file=(filename, data, mime))
            return meta.id

        return await self._guard(call)

    async def delete_file(self, file_id: str) -> None:
        try:
            await self.client.files.delete(file_id)
        except Exception as e:  # cleanup only
            log.info("could not delete uploaded file %s: %s", file_id, e)


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    """Swap the process client (tests inject one built on a recorded transport)."""
    global _llm
    _llm = llm


async def with_timeout[R](coro: Awaitable[R], seconds: float) -> R:
    try:
        return await asyncio.wait_for(coro, seconds)
    except TimeoutError as e:
        raise LLMUnavailable(f"no answer within {seconds}s") from e
