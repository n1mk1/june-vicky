"""Shared access-code gate: one code → signed HTTP-only cookie. Plus per-IP rate limits and the
daily LLM budget guard.
"""

import hmac
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel

from vicky import kv
from vicky.config import get_settings

router = APIRouter()


def _signer() -> TimestampSigner:
    return TimestampSigner(get_settings().cookie_secret, salt="vicky-access")


def make_token() -> str:
    return _signer().sign(b"workspace").decode()


def token_ok(token: str | None) -> bool:
    if not token:
        return False
    try:
        _signer().unsign(token, max_age=get_settings().cookie_max_age_s)
        return True
    except (BadSignature, SignatureExpired):
        return False


def client_ip(request: Request | WebSocket) -> str:
    # The rightmost X-Forwarded-For entry is the one our own proxy (Render / the web service) added;
    # earlier entries are client-controlled and would let anyone dodge the rate limit.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def _rate(key: str, limit: int, window_s: int = 60) -> bool:
    try:
        r = kv.client()
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, window_s)
        return n <= limit
    except Exception:  # Redis down: don't lock everyone out of a demo
        return True


async def require_access(request: Request) -> None:
    s = get_settings()
    if not token_ok(request.cookies.get(s.cookie_name)):
        raise HTTPException(status_code=401, detail="Enter the access code to continue.")
    if not await _rate(f"vicky:rl:{client_ip(request)}:{int(time.time() // 60)}", s.rate_limit_per_min):
        raise HTTPException(status_code=429, detail="Too many requests. Wait a minute and try again.")


async def require_budget() -> None:
    """402 on LLM routes once the day's spend reaches DAILY_USD_BUDGET. The offline path costs
    nothing, so without a key (or with LLM_MODE=offline) the guard never blocks."""
    from vicky import llm

    s = get_settings()
    if not llm.enabled():
        return
    try:
        spent = await kv.spend_today()
    except Exception:
        return
    if spent >= s.daily_usd_budget:
        raise HTTPException(status_code=402,
                            detail="Daily budget reached. Dashboards and reports still work; new VC turns resume tomorrow.")


class AccessIn(BaseModel):
    code: str


@router.post("/auth/access")
async def access(body: AccessIn, request: Request, response: Response) -> dict:
    s = get_settings()
    if not await _rate(f"vicky:rl:access:{client_ip(request)}", s.access_attempts_per_min):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
    if not hmac.compare_digest(body.code.strip().encode(), s.access_code.encode()):
        raise HTTPException(status_code=401, detail="That code didn't work.")
    response.set_cookie(s.cookie_name, make_token(), max_age=s.cookie_max_age_s, httponly=True,
                        samesite="lax", secure=s.cookie_secure, path="/")
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
