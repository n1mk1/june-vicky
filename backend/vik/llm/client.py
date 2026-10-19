"""Async Gemini wrapper: one place for model choice, thinking level, refusals, errors and spend.

- Each route names a model tier and an effort (TRD §5.2); the effort becomes Gemini's `thinking_level`. The
  court's agents have their own tiers: Vik, the orchestrator, runs on `model_vik` and the five investors on
  `model_investor`, both at low effort.
- Structured outputs are JSON-schema constrained (`response_json_schema`) and validated with the Pydantic model;
  tool loops run here, over plain function declarations, and end in the same structured answer.
- Why the model stopped is checked before any content is read: a blocked prompt or a safety stop →
  `LLMRefusal`, `MAX_TOKENS` → `LLMError`.
- The default is a free AI Studio key (`gemini_tier="free"`, free-tier models): calls cost nothing, so no dollar
  budget applies; instead `Pacer` keeps each model under `gemini_rpm` requests a minute, and after a 429 that
  model rests for the error's retryDelay, so calls drop to the offline path at once. The rest of this list is
  the paid tier (`gemini_tier="paid"`).
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
import copy
import io
import json
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import httpx
import pydantic
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from vik import kv
from vik.config import get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=pydantic.BaseModel)

# Requests up to this size carry a PDF inline; bigger ones go through the Files API first.
INLINE_MAX_BYTES = 15 * 1024 * 1024


# The last live call's outcome in this process, for GET /kb/status: a failing key or a spent budget would
# otherwise only show as agents quietly running offline.
HEALTH: dict[str, Any] = {"ok": None, "error": None, "at": None}


def note_health(e: BaseException | None) -> None:
    import time

    if e is None:
        HEALTH.update(ok=True, error=None, at=time.time())
    elif (
        not isinstance(e, LLMError)
        or isinstance(e, LLMUnavailable | BudgetExceeded)
        or "bad request" in str(e)
    ):
        # A malformed structured output is the model's, not the connection's: it doesn't count.
        HEALTH.update(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}", at=time.time())


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
    tier: Literal["vik", "investor", "deep", "fast", "tiny"]
    effort: Literal["low", "medium", "high"]
    max_tokens: int  # max_output_tokens: thinking counts against it too
    timeout_s: float | None = None  # whole call (or whole tool loop); None: the SDK's own timeout and retries


# TRD §5.2 roster. The court routes run inside /court/{sid}/answer and the pitch room, so each has a timeout
# after which the offline mind answers (the chair has its own, `chair_timeout_s`). Thinking counts against
# `max_tokens`, so even short replies leave room for it.
VIK_ROUTES = ("chair", "review", "judge", "verify", "probes")
INVESTOR_ROUTES = ("memo", "update_bid", "speak", "ask_knowledge")
ROUTES: dict[str, Route] = {
    # Vik, the orchestrator: picks who speaks, reviews every drafted line, scores each answer, schedules
    # and verifies the knowledge checks.
    "chair": Route("vik", "low", 4000),
    "review": Route("vik", "low", 4000, timeout_s=12),  # an investor's draft line, before it is spoken
    "judge": Route("vik", "low", 8000, timeout_s=20),  # Vik scores the answer
    "verify": Route("vik", "low", 4000, timeout_s=12),  # a knowledge answer against the notes
    "probes": Route(
        "vik", "low", 8000, timeout_s=30
    ),  # knowledge questions from the founder's notes, at start
    # The investors: research the company before the meeting (a read-only tool loop), then question the founder.
    "memo": Route("investor", "low", 16000, timeout_s=60),  # the whole tool loop
    "update_bid": Route("investor", "low", 4000, timeout_s=12),
    "speak": Route("investor", "low", 4000, timeout_s=12),
    "ask_knowledge": Route("investor", "low", 4000, timeout_s=12),
    # Utilities around the court and the rest of the app.
    "claims": Route("tiny", "low", 4000, timeout_s=12),
    "mapper": Route("fast", "medium", 8000),
    "doc_facts": Route("deep", "medium", 32000),
    "qa": Route("fast", "medium", 3000),
    "qa_rag": Route("tiny", "low", 3000),  # Ask Vik from retrieved chunks (docs/08-RAG.md)
    "qa_full": Route(
        "tiny", "medium", 4000
    ),  # the catch-all over the whole vault, only after the user accepts
    "persona": Route("fast", "medium", 8000),
    "kb_organize": Route("fast", "medium", 16000),
    "kb_hubs": Route("fast", "medium", 12000),
    "kb_profile": Route("fast", "medium", 6000),
    # The pitch room: checkable statements in a slide or a spoken segment, then each rated against the notes.
    "pitch_assertions": Route("tiny", "low", 2000, timeout_s=12),
    "pitch_kb": Route("fast", "low", 6000, timeout_s=20),
}

# USD per million tokens: input, output (thinking included), cached input. List prices, at the rates that
# apply from 2027 (Gemini 4 Argon and 3.8 Flash list a lower introductory rate until then), so the budget
# never under-counts.
PRICES: dict[str, tuple[float, float, float]] = {
    "gemini-4-argon": (4.0, 20.0, 0.20),
    "gemini-3.8-flash": (1.50, 7.50, 0.15),
    "gemini-3.6-flash": (1.50, 7.50, 0.15),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.1-pro-preview": (4.0, 18.0, 0.40),  # the >200k-token tier
}
UNKNOWN_PRICE = (4.0, 20.0, 0.40)  # an unlisted model is priced at the dearest rate


FREE = (0.0, 0.0, 0.0)


def free_tier() -> bool:
    return get_settings().gemini_tier == "free"


def price_of(model: str) -> tuple[float, float, float]:
    """List price, or nothing on a free-tier key (its limits are requests, not dollars)."""
    if free_tier():
        return FREE
    model = model.removeprefix("models/")
    for name in sorted(PRICES, key=len, reverse=True):
        if model == name or model.startswith(name + "-"):
            return PRICES[name]
    return UNKNOWN_PRICE


def usage_usd(model: str, usage: Any) -> float:
    """`prompt_token_count` includes the cached tokens, which are billed at the cached rate instead."""
    if usage is None:
        return 0.0
    p_in, p_out, p_cached = price_of(model)
    cached = getattr(usage, "cached_content_token_count", 0) or 0
    n_in = (getattr(usage, "prompt_token_count", 0) or 0) + (
        getattr(usage, "tool_use_prompt_token_count", 0) or 0
    )
    n_out = (getattr(usage, "candidates_token_count", 0) or 0) + (
        getattr(usage, "thoughts_token_count", 0) or 0
    )
    return (max(n_in - cached, 0) * p_in + n_out * p_out + cached * p_cached) / 1e6


def usage_tokens(usage: Any) -> int:
    return sum(
        getattr(usage, k, 0) or 0
        for k in ("prompt_token_count", "candidates_token_count", "thoughts_token_count")
    )


CHARS_PER_TOKEN = 3  # a generous token count from the prompt's JSON size
BYTES_PER_TOKEN = 200  # an attached document (a PDF is ~260 tokens a page)
MAX_PROMPT_TOKENS = 1_000_000  # no prompt is larger than the context window


def estimate_usd(model: str, prompt_tokens: float, max_tokens: int) -> float:
    """What one call can cost at most (near enough): the prompt at the uncached input rate plus a reply
    that uses all of `max_tokens`."""
    p_in, p_out, _ = price_of(model)
    return (min(prompt_tokens, MAX_PROMPT_TOKENS) * p_in + max_tokens * p_out) / 1e6


def prompt_tokens(params: dict[str, Any]) -> float:
    chars, doc_tokens = len(params.get("system") or ""), 0.0
    for m in params.get("messages") or []:
        content = m.get("content")
        if isinstance(content, str):
            chars += len(content)
            continue
        for b in content or []:
            if b.get("type") == "text":
                chars += len(b.get("text") or "")
            else:
                doc_tokens += b.get("tokens") or len(b.get("data") or b"") / BYTES_PER_TOKEN
    return chars / CHARS_PER_TOKEN + doc_tokens


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
    """The day's dollar budget is spent (never on a free-tier key, which costs nothing)."""
    if free_tier():
        return False
    return await spent_today() >= get_settings().daily_usd_budget


class Pacer:
    """Free-tier quotas are requests per minute and per day, per model: this process sends at most
    `gemini_rpm` requests a minute to each model (a request waits for a slot, within its route's timeout), and
    after the API answers 429 that model rests (the error's retryDelay, else `gemini_cooldown_s`), so calls
    fall back to the offline path at once instead of spending the rest of the quota on retries."""

    def __init__(self) -> None:
        self.sent: dict[str, deque[float]] = {}
        self.rest_until: dict[str, float] = {}

    async def acquire(self, model: str) -> None:
        now = time.monotonic()
        if (until := self.rest_until.get(model, 0.0)) > now:
            raise LLMUnavailable(f"rate limited: {model} rests for {until - now:.0f}s after a 429")
        s = get_settings()
        if s.gemini_tier != "free" or s.gemini_rpm <= 0:
            return
        while True:
            now = time.monotonic()
            q = self.sent.setdefault(model, deque())
            while q and now - q[0] >= 60:
                q.popleft()
            if len(q) < s.gemini_rpm:
                q.append(now)
                return
            await asyncio.sleep(60 - (now - q[0]) + 0.05)

    def rest(self, model: str, seconds: float) -> None:
        self.rest_until[model] = max(self.rest_until.get(model, 0.0), time.monotonic() + seconds)

    def reset(self) -> None:
        self.sent.clear()
        self.rest_until.clear()


PACER = Pacer()


def retry_delay(e: genai_errors.APIError) -> float | None:
    """The `retryDelay` of a 429's RetryInfo detail ("37s"), when the API sent one."""
    body = e.details.get("error", e.details) if isinstance(e.details, dict) else None
    items = body.get("details") if isinstance(body, dict) else None
    for d in items if isinstance(items, list) else []:
        delay = d.get("retryDelay") if isinstance(d, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                return None
    return None


def model_for(route: Route) -> str:
    s = get_settings()
    return {
        "vik": s.model_vik,
        "investor": s.model_investor,
        "deep": s.model_deep,
        "fast": s.model_fast,
        "tiny": s.model_tiny,
    }[route.tier]


# ---------------------------------------------------------------- tools and schemas


@dataclass(frozen=True)
class Tool:
    """A read-only function the model may call in a tool loop. `fn` takes the arguments as keywords and
    returns the result as a JSON string."""

    name: str
    description: str
    parameters: dict
    fn: Callable[..., Awaitable[str]]

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name, description=self.description, parameters_json_schema=self.parameters
        )


def tool(fn: Callable[..., Awaitable[str]], *, name: str, description: str, input_schema: dict) -> Tool:
    return Tool(name=name, description=description, parameters=input_schema, fn=fn)


def json_schema(model: type[pydantic.BaseModel]) -> dict:
    """The model's JSON schema with every `$ref` inlined and `$defs` dropped, for `response_json_schema`."""
    full = model.model_json_schema()
    defs = full.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = copy.deepcopy(defs[ref.removeprefix("#/$defs/")])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**target, **extra})
            return {k: walk(v) for k, v in node.items() if k != "default"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(full)


FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def parse_json[T: pydantic.BaseModel](schema: type[T], text: str) -> T:
    return schema.model_validate_json(FENCE.sub("", text or ""))


def _part(block: dict) -> types.Part:
    kind = block.get("type")
    if kind == "text":
        return types.Part(text=block.get("text") or "")
    if kind == "bytes":  # {type: bytes, data, mime_type}: a document carried inline
        return types.Part.from_bytes(data=block["data"], mime_type=block["mime_type"])
    if kind == "file":  # {type: file, uri, mime_type}: a document uploaded with `LLM.upload`
        return types.Part.from_uri(file_uri=block["uri"], mime_type=block["mime_type"])
    raise ValueError(f"unknown content block {kind!r}")


def to_contents(messages: list[dict]) -> list[types.Content]:
    """Chat-style messages (`role` user / assistant, `content` a string or a list of blocks) → Gemini contents."""
    out = []
    for m in messages:
        content = m.get("content")
        parts = (
            [types.Part(text=content or "")]
            if isinstance(content, str)
            else [_part(b) for b in content or []]
        )
        out.append(types.Content(role="model" if m.get("role") == "assistant" else "user", parts=parts))
    return out


def response_text(resp: Any) -> str:
    cands = getattr(resp, "candidates", None) or []
    parts = (getattr(getattr(cands[0], "content", None), "parts", None) or []) if cands else []
    return "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))


def function_calls(resp: Any) -> list[Any]:
    cands = getattr(resp, "candidates", None) or []
    parts = (getattr(getattr(cands[0], "content", None), "parts", None) or []) if cands else []
    return [p.function_call for p in parts if getattr(p, "function_call", None)]


REFUSED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY", "LANGUAGE"}


def _name(v: Any) -> str:
    return str(getattr(v, "value", v) or "")


class LLM:
    def __init__(self, client: genai.Client | None = None):
        self._client_obj = client
        self.spent = 0.0  # this process, for logs and tests

    @property
    def client(self) -> genai.Client:
        if self._client_obj is None:
            self._client_obj = genai.Client(
                api_key=get_settings().gemini_key(),
                # 429 is not retried here: on a free key a retry spends the quota again (see `Pacer`).
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(
                        attempts=3, http_status_codes=[408, 500, 502, 503, 504]
                    )
                ),
            )
        return self._client_obj

    # ------------------------------------------------------------ plumbing

    def params(self, route_name: str, system: str | list[str], messages: list[dict]) -> dict[str, Any]:
        route = ROUTES[route_name]
        parts = [system] if isinstance(system, str) else [p for p in system if p]
        return {
            "model": model_for(route),
            "max_tokens": route.max_tokens,
            "system": "\n\n".join(parts),
            "messages": messages,
            "thinking_level": route.effort,
        }

    def config(
        self,
        p: dict[str, Any],
        timeout: float | None,
        *,
        schema: type[pydantic.BaseModel] | None = None,
        tools: list[Tool] | None = None,
    ) -> types.GenerateContentConfig:
        cfg: dict[str, Any] = {
            "system_instruction": p["system"] or None,
            "max_output_tokens": p["max_tokens"],
            "thinking_config": types.ThinkingConfig(thinking_level=p["thinking_level"]),
        }
        if schema is not None:
            cfg["response_mime_type"] = "application/json"
            cfg["response_json_schema"] = json_schema(schema)
        if tools:
            cfg["tools"] = [types.Tool(function_declarations=[t.declaration() for t in tools])]
            cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        if timeout:  # one bound on the call, and no retries inside it
            cfg["http_options"] = types.HttpOptions(
                timeout=int(timeout * 1000), retry_options=types.HttpRetryOptions(attempts=1)
            )
        return types.GenerateContentConfig(**cfg)

    async def _record(self, resp: Any, model: str, held: float = 0.0) -> None:
        """Add the call's real cost to the day's spend, less what was reserved for it."""
        usd = usage_usd(getattr(resp, "model_version", None) or model, getattr(resp, "usage_metadata", None))
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

    @staticmethod
    def _check(resp: Any) -> Any:
        """Why the model stopped, before anyone reads the content."""
        feedback = getattr(resp, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise LLMRefusal(_name(feedback.block_reason), getattr(feedback, "block_reason_message", None))
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            raise LLMError("no candidate in the response")
        reason = _name(getattr(cands[0], "finish_reason", None))
        if reason in REFUSED:
            raise LLMRefusal(reason.lower(), getattr(cands[0], "finish_message", None))
        if reason == "MAX_TOKENS":
            raise LLMError("response hit max_tokens")
        if reason and reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            raise LLMError(f"generation stopped on {reason}")
        return resp

    async def _settle(self, resp: Any, model: str, hold: _Hold | None = None) -> Any:
        """Record spend, then check why the model stopped."""
        await self._record(resp, model, hold.take() if hold else 0.0)
        return self._check(resp)

    async def _guard(
        self,
        call: Callable[[], Awaitable[Any]],
        limit_s: float | None = None,
        hold: _Hold | None = None,
        reserve_usd: float = 0.0,
    ) -> Any:
        """Run one call (or tool loop) with errors mapped to `LLMError`. With a `hold`, `reserve_usd` is
        reserved first, and whatever is still held when the call ends (it failed) is handed back."""
        try:
            if free_tier():
                pass  # no dollar budget on a free key; the Pacer keeps to its quotas
            elif hold is None:
                if await over_budget():
                    raise BudgetExceeded("daily LLM budget reached")
            else:
                hold.usd = await self._reserve(reserve_usd)
            out = await self._mapped(call, limit_s)
        except Exception as e:
            note_health(e)
            raise
        finally:
            if hold is not None:
                await self._release(hold.take())
        note_health(None)
        return out

    async def _mapped(self, call: Callable[[], Awaitable[Any]], limit_s: float | None) -> Any:
        try:
            return await (asyncio.wait_for(call(), limit_s) if limit_s else call())
        except pydantic.ValidationError as e:
            raise LLMError(f"structured output did not validate: {e.errors()[:1]}") from e
        except genai_errors.ClientError as e:
            if (
                e.code == 400 and "api key" in str(e.message or e).lower()
            ):  # Gemini answers a bad key with 400
                raise LLMUnavailable("credentials rejected (API key not valid)") from e
            if e.code == 400:
                raise LLMError(f"bad request: {e.message or e}") from e
            if e.code in (401, 403):
                raise LLMUnavailable(f"credentials rejected ({e.code})") from e
            if e.code == 429:
                raise LLMUnavailable("rate limited") from e
            raise LLMUnavailable(f"API error {e.code}: {e.message or e}") from e
        except genai_errors.APIError as e:  # ServerError and anything else from the API
            raise LLMUnavailable(f"API error {e.code}") from e
        except httpx.TimeoutException as e:
            raise LLMUnavailable(f"timed out after {limit_s}s" if limit_s else "timed out") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"connection: {e}") from e
        except TimeoutError as e:
            raise LLMUnavailable(f"timed out after {limit_s}s" if limit_s else "timed out") from e

    async def _generate(self, p: dict[str, Any], contents: list[types.Content], cfg: Any) -> Any:
        model = p["model"]
        await PACER.acquire(model)
        try:
            return await self.client.aio.models.generate_content(model=model, contents=contents, config=cfg)
        except genai_errors.ClientError as e:
            if e.code == 429:
                PACER.rest(model, retry_delay(e) or get_settings().gemini_cooldown_s)
            raise

    @staticmethod
    def _estimate(p: dict[str, Any]) -> float:
        return estimate_usd(p["model"], prompt_tokens(p), p["max_tokens"])

    @staticmethod
    def _next_estimate(p: dict[str, Any], resp: Any) -> float:
        """The next call of a tool loop sends the last prompt again plus the reply and the tool results."""
        seen = usage_tokens(getattr(resp, "usage_metadata", None))
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
        cfg = self.config(p, timeout, schema=schema)
        hold = _Hold()

        async def call() -> T:
            resp = await self._settle(await self._generate(p, to_contents(messages), cfg), p["model"], hold)
            text = response_text(resp)
            if not text.strip():
                raise LLMError("no structured output in the response")
            return parse_json(schema, text)

        return await self._guard(call, timeout, hold, self._estimate(p))

    async def text(
        self,
        route: str,
        *,
        system: str | list[str],
        messages: list[dict],
        request_timeout_s: float | None = None,
    ) -> str:
        p = self.params(route, system, messages)
        timeout = self._timeout(route, request_timeout_s)
        cfg = self.config(p, timeout)
        hold = _Hold()

        async def call() -> str:
            resp = await self._settle(await self._generate(p, to_contents(messages), cfg), p["model"], hold)
            return response_text(resp).strip()

        return await self._guard(call, timeout, hold, self._estimate(p))

    async def run_tools(
        self,
        route: str,
        schema: type[T],
        *,
        system: str | list[str],
        messages: list[dict],
        tools: Iterable[Tool],
        max_iterations: int = 6,
    ) -> T:
        """A loop over read-only tools, ending in a structured `schema` answer. The route's timeout bounds the
        whole loop, and each further call reserves its own estimate before it is sent."""
        p = self.params(route, system, messages)
        timeout = self._timeout(route, None)
        tools = list(tools)
        by_name = {t.name: t for t in tools}
        cfg = self.config(p, timeout, schema=schema, tools=tools)
        hold = _Hold()

        async def call() -> T:
            contents = to_contents(messages)
            for _ in range(max_iterations):
                resp = await self._settle(await self._generate(p, contents, cfg), p["model"], hold)
                calls = function_calls(resp)
                if not calls:
                    text = response_text(resp)
                    if not text.strip():
                        raise LLMError("no structured output after the tool loop")
                    return parse_json(schema, text)
                contents.append(resp.candidates[0].content)  # as returned: it carries the thought signatures
                results = []
                for fc in calls:
                    out = await _run_tool(by_name.get(fc.name or ""), fc)
                    results.append(
                        types.Part.from_function_response(name=fc.name or "", response=_tool_response(out))
                    )
                contents.append(types.Content(role="user", parts=results))
                if not free_tier():
                    hold.usd = await self._reserve(
                        self._next_estimate(p, resp), "daily LLM budget reached during a tool loop"
                    )
            raise LLMError("tool loop ended on a tool call")

        return await self._guard(call, timeout, hold, self._estimate(p))

    async def upload(self, filename: str, data: bytes, mime: str) -> dict:
        """A document block for `messages`: inline when small, else through the Files API (delete it after with
        `delete_file(block["name"])`)."""
        if len(data) <= INLINE_MAX_BYTES:
            return {"type": "bytes", "data": data, "mime_type": mime}

        async def call() -> dict:
            f = await self.client.aio.files.upload(
                file=io.BytesIO(data),
                config=types.UploadFileConfig(mime_type=mime, display_name=filename[:100]),
            )
            return {
                "type": "file",
                "uri": f.uri,
                "mime_type": mime,
                "name": f.name,
                "tokens": len(data) / BYTES_PER_TOKEN,
            }

        return await self._guard(call)

    async def delete_file(self, name: str | None) -> None:
        if not name:
            return
        try:
            await self.client.aio.files.delete(name=name)
        except Exception as e:  # cleanup only
            log.info("could not delete uploaded file %s: %s", name, e)


async def _run_tool(t: Tool | None, fc: Any) -> str:
    """A tool's result, or an error the model can read and recover from."""
    if t is None:
        return json.dumps({"error": f"no tool called {fc.name!r}"})
    try:
        return await t.fn(**(fc.args or {}))
    except Exception as e:
        log.warning("tool %s failed: %s", t.name, e)
        return json.dumps({"error": f"{t.name} failed: {type(e).__name__}"})


def _tool_response(out: str) -> dict:
    """Gemini takes a function's result as an object: a JSON object as is, anything else under `result`."""
    try:
        val = json.loads(out)
    except (TypeError, ValueError):
        return {"result": out}
    return val if isinstance(val, dict) else {"result": val}


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
