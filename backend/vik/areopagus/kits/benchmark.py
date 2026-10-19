"""Benchmark: a metric next to sourced benchmarks only (`cite_source`); never an invented norm."""

from vik.areopagus.kits._base import Kit, Result, dump, enum, get, out, schema, tool
from vik.model.context import TruthContext
from vik.model.figures import Figure, MissingFigure, Source
from vik.model.sources import cite_source, sources

KIT = "Benchmark"

# metric id → source-library topics (exact topic match after `cite_source` filtering).
TOPICS: dict[str, list[str]] = {
    "arr": ["arr"],
    "mrr": ["arr"],
    "cmgr_12m": ["cmgr", "growth"],
    "cmgr_recent": ["cmgr", "growth"],
    "net_new_arr_l12m": ["growth"],
    "burn_multiple": ["burn_multiple", "efficiency"],
    "burn_multiple_ex_credits": ["burn_multiple", "efficiency"],
    "nrr": ["nrr"],
    "grr": ["grr"],
    "cac": ["cac"],
    "cac_payback_months": ["cac_payback"],
    "logo_churn_rate": ["churn"],
    "revenue_churn_rate": ["churn"],
    "magic_number": ["efficiency"],
    "revenue_growth": ["growth"],
    "revenue_growth_yoy": ["growth"],
    "gross_margin": ["gross_margin"],
    "gross_margin_incl_cs": ["gross_margin"],
    "gross_margin_incl_cs_l12m": ["gross_margin"],
    "burn": ["burn_rate"],
    "burn_incl_credits": ["burn_rate", "non_dilutive"],
    "cash_balance": ["runway"],
    "runway_months": ["runway", "default_alive"],
    "top_customer_share": ["concentration"],
}
KEEP = (
    "id",
    "publisher",
    "title",
    "claim",
    "url",
    "as_of",
    "verified",
    "verification_note",
    "stage",
    "business_model",
)
METRICS = list(TOPICS)


def _plain(v):
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    return str(v)


def clean_source(entry: dict) -> tuple[dict, list[dict]]:
    """A source entry with numeric thresholds split out (they become benchmark Figures) and other numbers as text."""
    thresholds = [t for t in entry.get("thresholds") or [] if isinstance(t, dict)]
    clean = _plain({k: entry.get(k) for k in KEEP if k in entry})
    return clean, thresholds


def _profile_ok(entry: dict, profile: dict) -> bool:
    for key in ("business_model", "stage"):
        vals = [str(v) for v in entry.get(key) or []]
        if vals and "any" not in vals and profile.get(key) and str(profile[key]) not in vals:
            return False
    return True


def sourced(topics: list[str], profile: dict) -> list[dict]:
    """`cite_source` hits whose topic list contains one of the topics exactly."""
    found: dict[str, dict] = {}
    for t in topics:
        for s in cite_source(t, profile):
            if t in [str(x).lower() for x in s.get("topic") or []]:
                found.setdefault(str(s.get("id")), s)
    return list(found.values())


def _matching_sources(metric: str, profile: dict) -> list[dict]:
    found: dict[str, dict] = {str(s.get("id")): s for s in sourced(TOPICS.get(metric, [metric]), profile)}
    for s in sources():
        if _profile_ok(s, profile) and any(
            isinstance(t, dict) and t.get("metric") == metric for t in s.get("thresholds") or []
        ):
            found.setdefault(str(s.get("id")), s)
    return list(found.values())


def _breaches(value: float, op: str, limit: float) -> bool:
    return (
        (op == ">" and value > limit)
        or (op == ">=" and value >= limit)
        or (op == "<" and value < limit)
        or (op == "<=" and value <= limit)
    )


def compare(ctx: TruthContext, metric: str) -> Result:
    f = get(ctx, metric)
    entries = _matching_sources(metric, ctx.profile)
    res = out(metric=f)
    res["metric_id"] = metric
    srcs, comps = [], []
    for e in entries:
        clean, ths = clean_source(e)
        srcs.append(clean)
        for t in ths:
            if (
                t.get("metric") != metric
                or not isinstance(t.get("value"), int | float)
                or not isinstance(f, Figure)
            ):
                continue
            op = str(t.get("op", ""))
            sid = str(e.get("id"))
            bench = Figure(
                id=f"benchmark.{sid}.{metric}",
                label=f"{e.get('publisher') or sid} threshold for {f.label}",
                value=float(t["value"]),
                unit=f.unit,
                formula=f"Sourced threshold: {f.label} {op} {t['value']} ({e.get('claim') or sid})",
                source=Source(
                    kind="benchmark",
                    ref=str(e.get("publisher") or sid),
                    url=e.get("url"),
                    source_id=sid,
                    verified=e.get("verified"),
                ),
                kind="benchmark",
                group="benchmark",
            )
            comps.append(
                {
                    "source_id": sid,
                    "op": op,
                    "threshold": dump(bench),
                    "flagged": _breaches(f.value, op, bench.value),
                }
            )
    res["sources"] = srcs
    if comps:
        res["comparisons"] = comps
    country = str(ctx.profile.get("country") or "").upper()
    if srcs and country and country not in ("US", "USA"):
        res["caution"] = (
            f"Most benchmark sources are US or portfolio data; label them as such for a {country} company."
        )
    if not srcs:
        label = f.label if isinstance(f, Figure | MissingFigure) and f.label else metric
        res["no_sourced_benchmark"] = (
            f"No sourced benchmark for {label} matches this company's business model and stage. "
            "Compare it with the company's own history instead; do not quote a norm."
        )
    return res


@tool(
    KIT,
    "benchmark_compare",
    "One engine metric next to sourced benchmarks from the source library (cite as [src:id]). Returns the metric "
    "Figure, source entries, comparisons[].threshold (benchmark Figures); or no_sourced_benchmark.",
    schema(metric=enum(METRICS, "Engine metric id to compare")),
)
def benchmark_compare(ctx: TruthContext, metric: str) -> Result:
    if metric not in TOPICS:
        raise ValueError(f"unknown metric '{metric}'")
    return compare(ctx, metric)


@tool(
    KIT,
    "benchmark_scan",
    "Every available engine metric that has a sourced benchmark, with the comparison. Returns comparisons per "
    "metric (metric Figure, source ids, benchmark Figures if any) and the metrics with no sourced benchmark.",
)
def benchmark_scan(ctx: TruthContext) -> Result:
    found, none = [], []
    for metric in METRICS:
        f = ctx.figures.get(metric)
        if not isinstance(f, Figure):
            continue
        r = compare(ctx, metric)
        if r.get("sources"):
            found.append(
                {
                    "metric_id": metric,
                    "metric": r["metric"],
                    "source_ids": [s.get("id") for s in r["sources"]],
                    **({"comparisons": r["comparisons"]} if r.get("comparisons") else {}),
                }
            )
        else:
            none.append(metric)
    return {
        "benchmarked": found,
        "no_sourced_benchmark": none,
        "note": "Call benchmark_compare for a metric to read the source claims; cite them as [src:id].",
    }


BENCHMARK = Kit(KIT, "Metrics against sourced benchmarks only.", [benchmark_compare, benchmark_scan])
