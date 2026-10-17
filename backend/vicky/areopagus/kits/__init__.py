"""Deterministic investor kits: read-only analyses over a TruthContext that return Figures.

Each kit is a set of `ToolDef`s (strict JSON-schema tools). The VC minds expose the kits named
by their persona; custom personas also get the kits implied by their heavy lenses. See
`_base.py` for the result convention (every number is a Figure; gaps are MissingFigures).
"""

from vicky.areopagus.kits._base import Kit, ToolDef
from vicky.areopagus.kits.benchmark import BENCHMARK
from vicky.areopagus.kits.cash import CASH
from vicky.areopagus.kits.channel import CHANNEL
from vicky.areopagus.kits.customer import CUSTOMER
from vicky.areopagus.kits.governance import GOVERNANCE
from vicky.areopagus.kits.market import MARKET_KIT
from vicky.areopagus.kits.milestone import MILESTONE
from vicky.areopagus.kits.product import PRODUCT
from vicky.areopagus.kits.quant_audit import QUANT_AUDIT
from vicky.areopagus.kits.red_team import RED_TEAM
from vicky.areopagus.kits.terms import TERMS
from vicky.model.context import TruthContext

KITS: dict[str, Kit] = {k.name: k for k in (QUANT_AUDIT, CUSTOMER, CHANNEL, GOVERNANCE, RED_TEAM, MARKET_KIT, TERMS,
                                            MILESTONE, BENCHMARK, CASH, PRODUCT)}

TOOLS: dict[str, ToolDef] = {t.name: t for k in KITS.values() for t in k.tools}

# Lens → kits a custom persona gets when it weights the lens at LENS_THRESHOLD or more.
LENS_KITS: dict[str, list[str]] = {
    "claims": ["QuantAudit"],
    "forecast": ["RedTeam", "Milestone"],
    "retention": ["QuantAudit", "Customer"],
    "unit_economics": ["QuantAudit", "Cash"],
    "concentration": ["Customer"],
    "runway": ["Cash", "Milestone"],
    "governance": ["Governance"],
    "market": ["Market"],
    "team": ["Milestone"],
    "product_tech": ["Product"],
    "terms_cap_table": ["Terms"],
    "impact": ["Governance"],
}
LENS_THRESHOLD = 0.6

_BY_KEY = {k.lower().replace("_", "").replace("-", "").replace(" ", ""): k for k in KITS}


def kit_name(name: str) -> str | None:
    """Canonical kit name for 'QuantAudit', 'quant_audit', 'red team' …; None if unknown."""
    return _BY_KEY.get(str(name).lower().replace("_", "").replace("-", "").replace(" ", ""))


def kit_tools(kit_names: list[str]) -> list[ToolDef]:
    """Tools of the named kits in order, without duplicates. Unknown names are ignored."""
    out: list[ToolDef] = []
    seen: set[str] = set()
    for n in kit_names:
        k = kit_name(n)
        if k is None:
            continue
        for t in KITS[k].tools:
            if t.name not in seen:
                seen.add(t.name)
                out.append(t)
    return out


def kits_for_lenses(lenses: dict[str, float]) -> list[str]:
    out: list[str] = []
    for lens, weight in sorted(lenses.items(), key=lambda kv: -float(kv[1] or 0)):
        if float(weight or 0) >= LENS_THRESHOLD:
            for k in LENS_KITS.get(lens, []):
                if k not in out:
                    out.append(k)
    return out


def registry_for(persona_kits: list[str], lenses: dict[str, float] | None = None) -> list[ToolDef]:
    """The persona's own kits first, then the kits implied by lenses weighted ≥ 0.6."""
    names = [k for n in persona_kits if (k := kit_name(n))]
    for k in kits_for_lenses(lenses or {}):
        if k not in names:
            names.append(k)
    return kit_tools(names)


def run_tool(name: str, ctx: TruthContext, args: dict | None = None) -> dict:
    t = TOOLS.get(name)
    if t is None:
        return {"error": f"unknown kit tool '{name}'"}
    return t.run(ctx, args)


__all__ = ["KITS", "LENS_KITS", "TOOLS", "Kit", "ToolDef", "kit_name", "kit_tools", "kits_for_lenses", "registry_for",
           "run_tool"]
