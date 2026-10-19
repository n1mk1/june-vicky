"""Bank of Canada daily rates: fetched from the Valet API and cached in Redis per currency and year.

A past year is fetched once it is over and kept; the current year counts as fresh for six hours.
Years are fetched together under one overall deadline, so a slow Valet API holds a request up for
DEADLINE_S at most. When the API can't be reached, whatever is cached is used, the failure is
remembered for FAILURE_TTL_S (no retry on every request), and a period with no rate stays
unconverted (see `vik.model.fx`).
"""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import UTC, date, datetime

import httpx

from vik import kv
from vik.model.fx import FOREIGN, VALET_URL, Rates, series_id

log = logging.getLogger(__name__)
TIMEOUT_S = 8.0
DEADLINE_S = 10.0  # for all the years of one load together
FAILURE_TTL_S = 5 * 60
FRESH_S = 6 * 3600
FIRST_YEAR = 2017  # the Valet daily series start in January 2017
# year → monotonic time until which a failed fetch isn't retried (per process).
_down: dict[int, float] = {}


def _key(code: str, year: int) -> str:
    return f"vik:fx:{code}:{year}"


async def _cached(code: str, year: int) -> dict | None:
    try:
        return await kv.get_json(_key(code, year))
    except Exception:  # Redis down or not connected: fetch instead
        return None


async def _store(code: str, year: int, obs: dict[str, float], now: datetime) -> None:
    try:
        await kv.set_json(_key(code, year), {"fetched": now.isoformat(), "obs": obs})
    except Exception as e:
        log.info("fx: rates for %s %d not cached: %s", code, year, e)


def _stale(entry: dict | None, year: int, now: datetime) -> bool:
    if entry is None:
        return True
    fetched = datetime.fromisoformat(entry["fetched"])
    if year < now.year:
        return fetched.year <= year  # fetched before the year was over
    return (now - fetched).total_seconds() > FRESH_S


async def fetch_year(client: httpx.AsyncClient, codes: list[str], year: int) -> dict[str, dict[str, float]]:
    url = VALET_URL.format(series=",".join(series_id(c) for c in codes))
    r = await client.get(url, params={"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"})
    r.raise_for_status()
    out: dict[str, dict[str, float]] = {c: {} for c in codes}
    for o in r.json().get("observations", []):
        for c in codes:
            try:
                out[c][o["d"]] = float((o.get(series_id(c)) or {})["v"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


async def load(
    codes: set[str], since: date | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> Rates:
    """Daily rates for `codes` from the start of `since`'s year (default: this year) to today."""
    wanted = sorted(c for c in codes if c in FOREIGN)
    rates = Rates()
    if not wanted:
        return rates
    now = datetime.now(UTC)
    years = range(max(FIRST_YEAR, min((since or now.date()).year, now.year)), now.year + 1)
    entries = {(c, y): await _cached(c, y) for c in wanted for y in years}
    todo: dict[int, list[str]] = defaultdict(list)
    for (c, y), e in entries.items():
        if _stale(e, y, now):
            todo[y].append(c)
    clock = time.monotonic()
    todo = {y: cs for y, cs in todo.items() if _down.get(y, 0.0) <= clock}
    if todo:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
            tasks = {y: asyncio.create_task(fetch_year(client, cs, y)) for y, cs in todo.items()}
            _, late = await asyncio.wait(tasks.values(), timeout=DEADLINE_S)
            for t in late:
                t.cancel()
            if late:
                await asyncio.wait(late)
            for y, t in tasks.items():
                e = TimeoutError(f"no answer within {DEADLINE_S:g} s") if t in late else t.exception()
                if e is not None:
                    _down[y] = time.monotonic() + FAILURE_TTL_S
                    log.warning("fx: Bank of Canada rates for %d not fetched (%s); using the cache", y, e)
                    continue
                _down.pop(y, None)
                for c, obs in t.result().items():
                    entries[(c, y)] = {"fetched": now.isoformat(), "obs": obs}
                    await _store(c, y, obs, now)
    for (c, _), e in entries.items():
        if e:
            rates.daily.setdefault(c, {}).update(e["obs"])
    return rates
