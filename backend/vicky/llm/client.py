"""Async Anthropic wrapper: one place for model choice, effort, fallbacks, refusals, errors and spend.

- Each route names a model tier and an effort (TRD §5.2); thinking stays adaptive (it can't be turned
  off on the 5.5 models) except the latency-bound chair, which uses `between_tools` on Sonnet 5.5.
- Structured outputs go through `messages.parse()`; tool loops through the SDK tool runner.
- `stop_reason` is checked before any content is read: `refusal` → `LLMRefusal`, `max_tokens` →
  `LLMError`. Opus/Sonnet requests opt into server-side fallbacks (`fallbacks: "default"`).
- Every response's usage is priced at list rates and added to the day's spend (Redis, and the Postgres
  `spend` table that is read when Redis is down); once the day's budget is spent, calls raise
  `BudgetExceeded` (and `auth.require_budget` turns LLM routes into 402). Before every call, including each
  call of a tool loop, an estimate of its cost (the prompt plus a full `max_tokens` reply) is reserved on the
  same counter and settled against the real cost after, so calls in flight see each other: once the spend
  and the reservations reach the budget, further calls are refused, and parallel loops overshoot the cap by
  one call between them, not one each. When neither store can be read, live calls fail closed.
- Routes on a request path carry a timeout (`Route.timeout_s`): one bound on the whole call, or on the whole
  tool loop, with no SDK retries inside it, so a slow API gives the offline mind's answer in seconds.

Callers treat every `LLMError` the same way: use the deterministic path instead.
"""

import asyncio
import json
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
    timeout_s: float | None = None  # whole call (or whole tool loop); None: the SDK's own timeout and retries


# TRD §5.2 roster. The court routes run inside /court/start and /court/{sid}/answer, so each has a timeout
# after which the offline mind answers (the chair has its own, `chair_timeout_s`).
ROUTES: dict[str, Route] = {
    "memo": Route("deep", "high", 16000, timeout_s=60),  # the whole tool loop
    "update_bid": Route("fast", "low", 4000, timeout_s=12),
    "speak": Route("fast", "medium", 4000, timeout_s=12),
    "chair": Route("fast", "low", 1024, thinking_off=True),
    "judge": Route("deep", "high", 8000, timeout_s=20),  # Vicky scores the answer
    "review": Route(
        "tiny", "low", 2000, timeout_s=12
    ),  # Vicky reviews an investor's draft line before it is spoken
    "probes": Route(
        "fast", "medium", 6000, timeout_s=30
    ),  # knowledge questions from the founder's notes, at start
    "ask_knowledge": Route("fast", "low", 2000, timeout_s=12),
    "verify": Route("tiny", "low", 2000, timeout_s=12),  # Vicky checks a knowledge answer against the notes
    "claims": Route("tiny", "low", 4000, timeout_s=12),
    "mapper": Route("fast", "medium", 8000),
    "doc_facts": Route("deep", "medium", 16000),
    "doc_parse": Route("deep", "medium", 16000),
    "qa": Route("fast", "medium", 3000),
    "qa_rag": Route("tiny", "low", 3000),  # Ask Vicky from retrieved chunks (docs/08-RAG.md)
    "qa_full": Route(
        "tiny", "medium", 4000
    ),  # the catch-all over the whole vault, only after the user accepts
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


CHARS_PER_TOKEN = 3  # a generous token count from the prompt's JSON size
MAX_PROMPT_TOKENS = 1_000_000  # no prompt is larger than the context window


def estimate_usd(model: str, prompt_tokens: float, max_tokens: int) -> float:
    """What one call can cost at most (near enough): the prompt at the uncached input rate plus a reply
    that uses all of `max_tokens`."""
    p_in, p_out, _, _ = price_of(model)
    return (min(prompt_tokens, MAX_PROMPT_TOKENS) * p_in + max_tokens * p_out) / 1e6


def prompt_tokens(params: dict[str, Any]) -> float:
    return len(json.dumps([params.get("system"), params.get("messages")], default=str)) / CHARS_PER_TOKEN


class _Hold:
    """The part of today's budget held for the call in flight, until it is settled or handed back."""

    def __init__(self) -> None:
        self.usd = 0.0

    def take(self) -> float:
        usd, self.usd = self.usd, 0.0
        return usd


async def spent_today() -> float:
    try:
        return await kv.spend_today()  # Redis, else the Postgres spend table
    except Exception as e:  # neither store can be read: a live call can't be shown to fit the budget
        log.warning("daily spend unreadable (%s); live LLM calls are off until it can be read", e)
        return float("inf")


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
        self.client = client or AsyncAnthropic(
            api_key=s.anthropic_api_key,
            max_retries=2,
            default_headers={"anthropic-workspace-id": s.anthropic_workspace_id}
            if s.anthropic_workspace_id
            else None,
        )
        self.spent = 0.0  # this process, for logs and tests

    # ------------------------------------------------------------ plumbing

    def params(self, route_name: str, system: str | list[str], messages: list[dict]) -> dict[str, Any]:
        route = ROUTES[route_name]
        model = model_for(route)
        p: dict[str, Any] = {
            "model": model,
            "max_tokens": route.max_tokens,
            "system": system_blocks(system),
            "messages": messages,
            "output_config": {"effort": route.effort},
        }
        if route.thinking_off and model.startswith("claude-sonnet-5-5"):
            p["thinking"] = {"type": "between_tools"}
        if get_settings().llm_server_fallbacks and supports_fallbacks(model):
            p["betas"] = [FALLBACK_BETA]
            p["fallbacks"] = "default"
        return p

    async def _record(self, msg: Any, held: float = 0.0) -> None:
        """Add the call's real cost to the day's spend, less what was reserved for it."""
        usd = usage_usd(getattr(msg, "model", ""), getattr(msg, "usage", None))
        self.spent += usd
        if usd <= 0 and held <= 0:
            return
        try:
            await kv.add_spend(usd - held, calls=1 if usd > 0 else 0)
        except Exception as e:  # spend tracking must never break a turn
            log.warning("could not record LLM spend: %s", e)

    async def _reserve(self, usd: float, why: str = "daily LLM budget reached") -> float:
        """Hold `usd` of today's budget for a call about to be sent, and return what is held. Raises
        `BudgetExceeded` when the spend and the calls already in flight have used the budget up."""
        try:
            total = await kv.add_spend(usd, calls=0)
        except Exception as e:  # neither store can be written: the plain check (fails closed if unreadable)
            log.warning("could not reserve LLM spend (%s); checking the budget without a reservation", e)
            if await over_budget():
                raise BudgetExceeded(why) from None
            return 0.0
        if total - usd >= get_settings().daily_usd_budget:
            await self._release(usd)
            raise BudgetExceeded(why)
        return usd

    async def _release(self, usd: float) -> None:
        if usd <= 0:
            return
        try:
            await kv.add_spend(-usd, calls=0)
        except Exception as e:
            log.warning("could not hand back reserved LLM spend: %s", e)

    async def _settle(self, msg: Any, hold: _Hold | None = None) -> Any:
        """Record spend, then check why the model stopped before anyone reads the content."""
        await self._record(msg, hold.take() if hold else 0.0)
        reason = getattr(msg, "stop_reason", None)
        if reason == "refusal":
            d = getattr(msg, "stop_details", None)
            raise LLMRefusal(getattr(d, "category", None), getattr(d, "explanation", None))
        if reason == "max_tokens":
            raise LLMError("response hit max_tokens")
        if reason == "pause_turn":
            raise LLMError("turn paused before finishing")
        return msg

    async def _guard(
        self,
        call: Callable[[], Awaitable[Any]],
        limit_s: float | None = None,
        hold: _Hold | None = None,
        reserve_usd: float = 0.0,
    ) -> Any:
        """Run one call (or tool loop) with errors mapped to `LLMError`. With a `hold`, `reserve_usd` is
        reserved first, and whatever is still held when the call ends (it failed) is handed back."""
        if hold is None:
            if await over_budget():
                raise BudgetExceeded("daily LLM budget reached")
        else:
            hold.usd = await self._reserve(reserve_usd)
        try:
            return await (asyncio.wait_for(call(), limit_s) if limit_s else call())
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
            raise LLMUnavailable(f"timed out after {limit_s}s" if limit_s else "timed out") from e
        finally:
            if hold is not None:
                await self._release(hold.take())

    def _client(self, timeout: float | None):
        return self.client.with_options(timeout=timeout, max_retries=0) if timeout else self.client

    @staticmethod
    def _estimate(p: dict[str, Any]) -> float:
        return estimate_usd(p["model"], prompt_tokens(p), p["max_tokens"])

    @staticmethod
    def _next_estimate(p: dict[str, Any], msg: Any) -> float:
        """The next call of a tool loop sends the last prompt again plus the reply and the tool results."""
        u = getattr(msg, "usage", None)
        seen = sum(
            getattr(u, k, 0) or 0
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        )
        return estimate_usd(p["model"], max(seen, prompt_tokens(p)) + 2000, p["max_tokens"])

    @staticmethod
    def _timeout(route: str, override: float | None) -> float | None:
        return override or ROUTES[route].timeout_s

    # ------------------------------------------------------------ calls

    async def parse(
        self,
        route: str,
        schema: type[T],
        *,
        system: str | list[str],
        messages: list[dict],
        request_timeout_s: float | None = None,
    ) -> T:
        """One structured-output call; returns the validated `schema` instance."""
        p = self.params(route, system, messages)
        timeout = self._timeout(route, request_timeout_s)
        hold = _Hold()

        async def call() -> T:
            msg = await self._client(timeout).beta.messages.parse(output_format=schema, **p)
            await self._settle(msg, hold)
            out = msg.parsed_output
            if out is None:
                raise LLMError("no structured output in the response")
            return out

        return await self._guard(call, timeout, hold, self._estimate(p))

    async def text(
        self,
        route: str,
        *,
        system: str | list[str],
        messages: list[dict],
        request_timeout_s: float | None = None,
    ) -> str:
        msg = await self.message(route, system=system, messages=messages, request_timeout_s=request_timeout_s)
        return "".join(b.text for b in msg.content if b.type == "text").strip()

    async def message(
        self,
        route: str,
        *,
        system: str | list[str],
        messages: list[dict],
        request_timeout_s: float | None = None,
    ) -> Any:
        """A plain call that returns the whole message (used for citations, which can't be combined
        with structured outputs)."""
        p = self.params(route, system, messages)
        timeout = self._timeout(route, request_timeout_s)
        hold = _Hold()

        async def call() -> Any:
            return await self._settle(await self._client(timeout).beta.messages.create(**p), hold)

        return await self._guard(call, timeout, hold, self._estimate(p))

    async def run_tools(
        self,
        route: str,
        schema: type[T],
        *,
        system: str | list[str],
        messages: list[dict],
        tools: Iterable[Any],
        max_iterations: int = 6,
    ) -> T:
        """Tool runner over read-only tools, ending in a structured `schema` answer. The route's timeout
        bounds the whole loop, and each further call reserves its own estimate before it is sent."""
        p = self.params(route, system, messages)
        timeout = self._timeout(route, None)
        hold = _Hold()

        async def call() -> T:
            runner = self._client(timeout).beta.messages.tool_runner(
                tools=list(tools), output_format=schema, max_iterations=max_iterations, **p
            )
            last = None
            async for msg in runner:
                last = msg
                await self._record(msg, hold.take())
                if msg.stop_reason == "refusal":
                    d = getattr(msg, "stop_details", None)
                    raise LLMRefusal(getattr(d, "category", None), getattr(d, "explanation", None))
                if msg.stop_reason == "tool_use":  # the runner will call the model again
                    hold.usd = await self._reserve(
                        self._next_estimate(p, msg), "daily LLM budget reached during a tool loop"
                    )
            if last is None:
                raise LLMError("tool runner returned nothing")
            if last.stop_reason != "end_turn":
                raise LLMError(f"tool loop ended on {last.stop_reason}")
            if last.parsed_output is None:
                raise LLMError("no structured output after the tool loop")
            return last.parsed_output

        return await self._guard(call, timeout, hold, self._estimate(p))

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
