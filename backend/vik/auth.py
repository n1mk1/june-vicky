"""Shared access-code gate: one code → signed HTTP-only cookie. Plus per-IP rate limits and the
daily LLM budget guard.

The cookie signs a tag derived from ACCESS_CODE, so changing the code revokes every cookie issued
under the old one (rotating COOKIE_SECRET does too).
"""

import hashlib
import hmac
import logging
import time
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_address

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel

from vik import kv
from vik.config import get_settings, parse_cidrs

router = APIRouter()
log = logging.getLogger(__name__)
_untrusted_seen: set[str] = set()


def _signer() -> TimestampSigner:
    return TimestampSigner(get_settings().cookie_secret, salt="vik-access")


def code_tag() -> bytes:
    """Names the access code a token was issued under without revealing it."""
    s = get_settings()
    return (
        hmac.new(s.cookie_secret.encode(), s.access_code.encode(), hashlib.sha256).hexdigest()[:16].encode()
    )


def make_token() -> str:
    return _signer().sign(code_tag()).decode()


def token_ok(token: str | None) -> bool:
    if not token:
        return False
    try:
        value = _signer().unsign(token, max_age=get_settings().cookie_max_age_s)
    except (BadSignature, SignatureExpired):
        return False
    return hmac.compare_digest(value, code_tag())


@lru_cache(maxsize=8)
def _networks(cidrs: str) -> tuple[IPv4Network | IPv6Network, ...]:
    return parse_cidrs(cidrs)


def _trusted(host: str, networks: tuple[IPv4Network | IPv6Network, ...]) -> bool:
    try:
        ip = ip_address(host.strip().strip("[]"))
    except ValueError:
        return False
    return any(ip.version == n.version and ip in n for n in networks)


def client_ip(request: Request | WebSocket) -> str:
    """The address rate limits count against. X-Forwarded-For is read only when the direct peer is a
    trusted proxy (TRUSTED_PROXY_CIDRS: Render's edge and private network, docker, localhost); then the
    client is the rightmost forwarded address that isn't one of those proxies. Entries further left
    are whatever the client sent, so trusting them would let anyone dodge the limits."""
    peer = request.client.host if request.client else ""
    networks = _networks(get_settings().trusted_proxy_cidrs)
    fwd = request.headers.get("x-forwarded-for")
    if fwd and not _trusted(peer, networks) and peer not in _untrusted_seen and len(_untrusted_seen) < 16:
        # Once per address: if a real proxy shows up here, add its range to TRUSTED_PROXY_CIDRS.
        _untrusted_seen.add(peer)
        log.info("X-Forwarded-For from %s ignored: not in TRUSTED_PROXY_CIDRS", peer)
    if not fwd or not _trusted(peer, networks):
        return peer or "unknown"
    hops = [h.strip() for h in fwd.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _trusted(hop, networks):
            return hop
    return hops[0] if hops else peer or "unknown"


async def _rate(key: str, limit: int, window_s: int = 60) -> bool:
    try:
        # One round trip, and the TTL is set whenever the key has none, so a key can't outlive its window.
        async with kv.client().pipeline(transaction=True) as pipe:
            n, _ = await pipe.incr(key).expire(key, window_s, nx=True).execute()
        return n <= limit
    except Exception:  # Redis down: don't lock everyone out of a demo
        return True


def _failures_key() -> str:
    return f"vik:rl:access-failures:{int(time.time() // 60)}"


async def _too_many_failures(limit: int) -> bool:
    """A global cap on wrong codes per minute, whatever address they claim to come from."""
    try:
        return int(await kv.client().get(_failures_key()) or 0) >= limit
    except Exception:
        return False


async def _count_failure() -> None:
    try:
        key = _failures_key()
        async with kv.client().pipeline(transaction=True) as pipe:
            await pipe.incr(key).expire(key, 120, nx=True).execute()
    except Exception:
        pass


async def require_access(request: Request) -> None:
    s = get_settings()
    if not token_ok(request.cookies.get(s.cookie_name)):
        raise HTTPException(status_code=401, detail="Enter the access code to continue.")
    if not await _rate(f"vik:rl:{client_ip(request)}:{int(time.time() // 60)}", s.rate_limit_per_min):
        raise HTTPException(status_code=429, detail="Too many requests. Wait a minute and try again.")


async def require_budget() -> None:
    """402 on LLM routes once the day's spend reaches DAILY_USD_BUDGET. The offline path costs
    nothing, so without a key (or with LLM_MODE=offline) the guard never blocks; neither does a free-tier
    Gemini key, whose limits are requests (the LLM client paces them), not dollars."""
    from vik import llm

    s = get_settings()
    if not llm.enabled() or s.gemini_tier == "free":
        return
    try:
        spent = await kv.spend_today()
    except Exception:
        return
    if spent >= s.daily_usd_budget:
        raise HTTPException(
            status_code=402,
            detail="Daily budget reached. Dashboards and reports still work; new VC turns resume tomorrow.",
        )


class AccessIn(BaseModel):
    code: str


@router.post("/auth/access")
async def access(body: AccessIn, request: Request, response: Response) -> dict:
    s = get_settings()
    limited = not await _rate(f"vik:rl:access:{client_ip(request)}", s.access_attempts_per_min)
    if limited or await _too_many_failures(s.access_failures_per_min):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
    if not hmac.compare_digest(body.code.strip().encode(), s.access_code.encode()):
        await _count_failure()
        raise HTTPException(status_code=401, detail="That code didn't work.")
    response.set_cookie(
        s.cookie_name,
        make_token(),
        max_age=s.cookie_max_age_s,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )
    return {"ok": True}


@router.get("/auth/session")
async def session(request: Request) -> dict:
    return {"ok": token_ok(request.cookies.get(get_settings().cookie_name))}


@router.post("/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(get_settings().cookie_name, path="/")
    return {"ok": True}


Gate = Depends(require_access)
Budget = Depends(require_budget)
