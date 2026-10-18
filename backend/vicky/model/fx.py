"""Currency conversion at Bank of Canada rates.

The Bank of Canada publishes one daily average rate per currency, in Canadian dollars per unit.
Every other pair is a cross rate through CAD. A period's flow (revenue, costs) converts at the
average of that period's daily rates; a stock (cash, pipeline) at the last rate in the period.
A period after the latest published rate (a forecast, or this month before any rate is out)
converts at the latest rate. A period with no rates at all is not converted, never guessed.

Pure code: `vicky.services.fx` fetches and caches the rates.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from vicky.model.currencies import CURRENCIES

SOURCE_NAME = "Bank of Canada"
SOURCE_URL = "https://www.bankofcanada.ca/rates/exchange/daily-exchange-rates/"
VALET_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
FOREIGN = tuple(c for c in CURRENCIES if c != "cad")

How = Literal["avg", "end"]
MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def series_id(code: str) -> str:
    return f"FX{code.upper()}CAD"


def period_range(period: str) -> tuple[date, date] | None:
    """First and last day of a "YYYY-MM", "YYYY-Qn" or "YYYY" period."""
    try:
        if "-Q" in period:
            y, q = period.split("-Q")
            first = (int(q) - 1) * 3 + 1
            return date(int(y), first, 1), date(int(y), first + 2, calendar.monthrange(int(y), first + 2)[1])
        if "-" in period:
            y, m = period.split("-")
            return date(int(y), int(m), 1), date(int(y), int(m), calendar.monthrange(int(y), int(m))[1])
        return date(int(period), 1, 1), date(int(period), 12, 31)
    except (ValueError, IndexError):
        return None


def period_label(period: str) -> str:
    if "-Q" in period or "-" not in period:
        return period
    y, m = period.split("-")
    return f"{MONTH_ABBR[int(m)]} {y}"


@dataclass(frozen=True)
class FxRate:
    value: float  # a `src` amount × value = the `dst` amount
    src: str
    dst: str
    basis: str  # e.g. "Jan 2025 average of 21 daily rates", "rate on 2025-01-31", "latest rate, 2026-10-16"

    def note(self) -> str:
        return f"{self.src.upper()}→{self.dst.upper()} ×{self.value:.6g} ({SOURCE_NAME}, {self.basis})"


@dataclass
class Rates:
    daily: dict[str, dict[str, float]] = field(default_factory=dict)  # code → {ISO date: CAD per unit}

    def cad_per(self, code: str, period: str | None, how: How = "avg") -> tuple[float, str] | None:
        if code == "cad":
            return 1.0, ""
        obs = self.daily.get(code) or {}
        if not obs:
            return None
        latest = max(obs)
        rng = period_range(period) if period else None
        if rng is None:
            return obs[latest], f"latest rate, {latest}"
        lo, hi = rng[0].isoformat(), rng[1].isoformat()
        inside = sorted((d, v) for d, v in obs.items() if lo <= d <= hi)
        if inside:
            if how == "end":
                d, v = inside[-1]
                return v, f"rate on {d}"
            return sum(v for _, v in inside) / len(
                inside
            ), f"{period_label(period)} average of {len(inside)} daily rates"
        if lo > latest:
            return obs[latest], f"latest rate, {latest}"
        return None

    def rate(self, src: str, dst: str, period: str | None = None, how: How = "avg") -> FxRate | None:
        """The rate converting `src` into `dst` for a period, or None when it isn't published."""
        if src == dst:
            return FxRate(1.0, src, dst, "same currency")
        a, b = self.cad_per(src, period, how), self.cad_per(dst, period, how)
        if a is None or b is None or b[0] == 0:
            return None
        return FxRate(a[0] / b[0], src, dst, a[1] or b[1])


def needed_codes(*units: object) -> set[str]:
    """The foreign currencies (Bank of Canada series) a set of units needs."""
    return {str(u).lower() for u in units if str(u).lower() in FOREIGN}


def earliest_date(periods: list[str]) -> date | None:
    starts = [r[0] for p in periods if (r := period_range(p))]
    return min(starts) if starts else None
