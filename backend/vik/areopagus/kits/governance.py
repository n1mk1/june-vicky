"""Governance: finance function, dependence on tax credits and grants, and country rules.

Country rules come from `data/playbooks/geo/<country>.md` (front-matter + bullet lines) and
are returned as questions to verify with an advisor, never as tax or legal advice.
"""

import re
from pathlib import Path

import yaml

from vik import DATA_DIR
from vik.areopagus.kits._base import (
    Kit,
    Result,
    cell_figure,
    column_figure,
    derived,
    get,
    last_n_months,
    matching_columns,
    missing,
    out,
    sum_figure,
    tool,
)
from vik.model.context import TruthContext

KIT = "Governance"
GEO_DIR = DATA_DIR / "playbooks" / "geo"
VERIFY = "(verify with an advisor)"
MAX_RULES = 40

FINANCE = (
    r"bookkeep|accounting|accountant|finance|\bcfo\b|controller|audit|professional[ _]?fees|legal|tax[ _]prep"
)
COUNTRY_FILES = {"CA": "CA", "CAN": "CA", "US": "US", "USA": "US", "GB": "UK", "UK": "UK", "GBR": "UK"}

FINANCE_QUESTIONS = [
    "Who keeps the books, and how many days after month end are they closed?",
    "Are the financial statements reviewed or audited by an outside accountant?",
    "Who sits on the board today, and how often does it meet?",
    "Who signs off on spending above a set limit?",
    "Which legal entity owns the IP, and have all founders and contractors assigned theirs to it?",
    "Who prepares tax-credit or grant claims, and has any claim been reviewed or adjusted?",
]


@tool(
    KIT,
    "governance_finance_function",
    "Signals about the finance function: G&A share of opex, spend on bookkeeping / accounting / professional fees "
    "found in the data, and headcount. Returns Figures: opex_share_g_and_a, finance_spend[], headcount; plus "
    "questions as plain strings.",
)
def finance_function(ctx: TruthContext) -> Result:
    m = ctx.model
    parts: dict = {"opex_share_g_and_a": get(ctx, "opex_share_g_and_a")}
    p = m.latest("headcount.total")
    if p:
        parts["headcount"] = cell_figure(ctx, "headcount.total", p, fid="headcount.total", label="Headcount")
    ps = m.periods[-max(1, 12 // m.months_per_period) :]
    spend = []
    for i, (ds, col) in enumerate(matching_columns(ctx, FINANCE), start=1):
        f = column_figure(ctx, ds, col, ps, f"governance.finance_col{i}_l12m", f"'{col}', last 12 months")
        if f is not None:
            spend.append(f.model_dump(mode="json"))
    res = out(**parts)
    if spend:
        res["finance_spend"] = spend
    else:
        res.setdefault("missing", []).append(
            missing(
                "governance.finance_spend",
                "Finance and accounting spend",
                ["bookkeeping / accounting expense line"],
                "No bookkeeping, accounting or professional-fees line in the data",
            ).model_dump(mode="json")
        )
    res["questions"] = list(FINANCE_QUESTIONS)
    return res


@tool(
    KIT,
    "governance_credit_dependence",
    "How much of the burn tax credits and grants cover. Returns Figures: credits_l12m, burn_before_credits_l12m, "
    "credit_share_of_burn, burn, burn_incl_credits, burn_multiple, burn_multiple_ex_credits.",
)
def credit_dependence(ctx: TruthContext) -> Result:
    m = ctx.model
    parts: dict = {
        k: get(ctx, k) for k in ("burn", "burn_incl_credits", "burn_multiple", "burn_multiple_ex_credits")
    }
    if not m.has("non_dilutive_income"):
        return out(
            [
                missing(
                    "governance.credits_l12m",
                    "Tax credits and grants",
                    ["non_dilutive_income"],
                    "No tax-credit or grant income in the data",
                )
            ],
            **parts,
        )
    ps = [p for p in last_n_months(ctx, "net_income", 12) if m.value("net_income", p) is not None]
    if not ps:
        return out(
            [
                missing(
                    "governance.credits_l12m",
                    "Tax credits and grants",
                    ["net_income"],
                    "Needs net income for the window",
                )
            ],
            **parts,
        )
    credits = sum_figure(
        ctx, "non_dilutive_income", ps, "governance.credits_l12m", "Tax credits and grants, last 12 months"
    )
    ni = sum_figure(ctx, "net_income", ps, "governance.net_income_l12m", "Net income, last 12 months")
    before = derived(
        "governance.burn_before_credits_l12m",
        "Net burn before credits, last 12 months",
        -(ni.value - credits.value),
        ctx.currency,
        f"−(net income {ni.display} − credits {credits.display})",
        [ni, credits],
        period=ni.period,
    )
    parts.update(credits_l12m=credits, burn_before_credits_l12m=before)
    if before.value > 0:
        parts["credit_share_of_burn"] = derived(
            "governance.credit_share_of_burn",
            "Share of pre-credit burn covered by credits and grants",
            credits.value / before.value,
            "pct",
            f"credits {credits.display} ÷ burn before credits {before.display}",
            [credits, before],
            period=ni.period,
        )
    return out(**parts)


def country_code(profile: dict) -> str:
    return COUNTRY_FILES.get(str(profile.get("country") or "").strip().upper(), "generic")


def _strings(v):
    if isinstance(v, dict):
        return {str(k): _strings(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_strings(x) for x in v]
    return "" if v is None else str(v)


def parse_playbook(text: str) -> tuple[dict, list[str]]:
    """Front-matter (all values as strings) and every bullet line, continuation lines joined."""
    front: dict = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = yaml.safe_load(text[3:end]) or {}
            front = _strings(raw) if isinstance(raw, dict) else {}
            body = text[end + 4 :]
    rules: list[str] = []
    section = ""
    current: list[str] | None = None
    in_code = False

    def flush() -> None:
        nonlocal current
        if current:
            t = re.sub(r"\s+", " ", " ".join(current)).strip().replace("**", "").replace("`", "")
            if t:
                rules.append(f"{section}: {t}" if section else t)
        current = None

    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        if s.startswith("#"):
            flush()
            section = s.lstrip("#").strip()
            continue
        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            flush()
            current = [re.sub(r"^\s*([-*+]|\d+\.)\s+", "", line)]
        elif current is not None and s and line[:1].isspace():
            current.append(s)
        else:
            flush()
    flush()
    return front, rules


def _with_verify(rule: str) -> str:
    return rule if "verify" in rule.lower() else f"{rule.rstrip()} {VERIFY}"


@tool(
    KIT,
    "governance_country_rules",
    "Country rules from the company profile's country playbook (tax credits, grants, control status, local rules), "
    "each to verify with an advisor. Returns plain strings in rules[] and the playbook front-matter; no Figures.",
)
def country_rules(ctx: TruthContext) -> Result:
    code = country_code(ctx.profile)
    path: Path | None = None
    for name in (code, "generic"):
        p = GEO_DIR / f"{name}.md"
        if p.exists():
            path = p
            break
    country = str(ctx.profile.get("country") or "unknown")
    if path is None:
        return {
            "country": country,
            "playbook": None,
            "rules": [],
            "missing": [
                missing(
                    "governance.country_rules",
                    "Country rules",
                    [f"playbooks/geo/{code}.md"],
                    "No country playbook is available yet",
                ).model_dump(mode="json")
            ],
            "note": "No country rules on file; ask the founder which programmes and rules apply and verify with an advisor.",
        }
    front, rules = parse_playbook(path.read_text(encoding="utf-8"))
    res: Result = {
        "country": country,
        "playbook": f"geo/{path.name}",
        "front_matter": front,
        "rules": [_with_verify(r) for r in rules[:MAX_RULES]],
        "note": "Questions to raise with the founder, not tax or legal advice. Every rule must be verified with an advisor.",
    }
    if path.stem != code:
        res["fallback"] = f"No playbook for {country}; using the generic playbook"
    return res


GOVERNANCE = Kit(
    KIT,
    "Finance function, tax-credit dependence and country-specific mandate rules (verify with an advisor).",
    [finance_function, credit_dependence, country_rules],
)
