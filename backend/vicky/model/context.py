"""TruthContext: everything code knows about one engagement's confirmed source of truth.

Built once per TruthPack version and passed to metrics consumers, kits, the dashboard
evaluator and agents. Agents never see raw data; they call tools that read from here.
"""

from dataclasses import dataclass, field
from typing import Any

from vicky.model.currencies import CURRENCY_CODES, norm_currency
from vicky.model.figures import Fact, Figure, MissingFigure
from vicky.model.financials import CanonicalModel, DatasetInput, build_model
from vicky.model.fx import Rates, period_range
from vicky.model.metrics import compute_metrics, fact_figures
from vicky.model.truth import AttackItem, attack_list


@dataclass
class TruthContext:
    profile: dict[str, Any]
    model: CanonicalModel
    figures: dict[str, Figure | MissingFigure]
    facts: list[Fact]
    attack: list[AttackItem] = field(default_factory=list)
    version: int = 1
    truthpack_id: str | None = None
    engagement_id: str | None = None

    def figure(self, fid: str) -> Figure | None:
        f = self.figures.get(fid)
        return f if isinstance(f, Figure) else None

    def available(self) -> list[Figure]:
        return [f for f in self.figures.values() if isinstance(f, Figure)]

    def missing(self) -> list[MissingFigure]:
        return [f for f in self.figures.values() if isinstance(f, MissingFigure)]

    @property
    def currency(self) -> str:
        return self.model.currency

    @property
    def company(self) -> str:
        return self.profile.get("name") or "the company"


def convert_facts(facts: list[Fact], currency: str, fx: Rates | None) -> list[Fact]:
    """Facts in another currency, converted at the rate for their period (the latest rate when they
    have none). A fact with no published rate keeps its own currency."""
    out = []
    for f in facts:
        src = f.unit.lower()
        if src in CURRENCY_CODES and src != currency and fx is not None:
            period = f.period if f.period and period_range(f.period) else None
            r = fx.rate(src, currency, period, "avg")
            if r is not None:
                f = f.model_copy(update={
                    "value": f.value * r.value, "unit": currency,
                    "note": "; ".join(x for x in (f.note, f"converted {r.note()}") if x),
                    "source": f.source.model_copy(update={"ref": f"{f.source.ref} · converted {r.note()}".lstrip(" ·")})})
        out.append(f)
    return out


def convert_profile(profile: dict[str, Any], currency: str, fx: Rates | None) -> dict[str, Any]:
    """The profile's money values (round size) moved into `currency` at the latest rate."""
    src = norm_currency(profile.get("currency"))
    rs = profile.get("round_size")
    if src == currency or not isinstance(rs, int | float) or isinstance(rs, bool):
        return profile
    r = fx.rate(src, currency) if fx else None
    if r is None:
        return {**profile, "round_size": None}  # no rate: the round size can't be shown in this currency
    return {**profile, "round_size": rs * r.value, "round_size_fx": r.note()}


def build_context(datasets: list[DatasetInput], facts: list[Fact], profile: dict[str, Any], version: int = 1,
                  truthpack_id: str | None = None, engagement_id: str | None = None,
                  deck_checks: list | None = None, fx: Rates | None = None, currency: str | None = None) -> TruthContext:
    """`currency` is the one every money figure comes out in: the profile's (the reporting currency)
    unless a view asks for another. Anything in a different currency converts at `fx` rates."""
    target = norm_currency(currency or profile.get("currency"))
    facts = convert_facts(facts, target, fx)
    reporting = norm_currency(profile.get("currency"))
    profile = {**convert_profile(profile, target, fx), "currency": target, "reporting_currency": reporting}
    model = build_model(datasets, target, profile.get("granularity"), fx=fx)
    figures = compute_metrics(model, facts, profile)
    for f in fact_figures([x for x in facts if x.status == "confirmed"], exclude=set(figures)):
        figures.setdefault(f.id, f)
    attack = attack_list(figures, facts, profile, deck_checks)
    return TruthContext(profile=profile, model=model, figures=figures, facts=facts, attack=attack, version=version,
                        truthpack_id=truthpack_id, engagement_id=engagement_id)


def sample_context(sample_id: str) -> TruthContext:
    """Build a context straight from a sample folder (tests, evals, offline previews)."""
    from vicky.samples import load_sample

    s = load_sample(sample_id)
    inputs = []
    for f in s.files:
        for ds in f.datasets:
            mapping = s.mappings[f"{f.filename}#{ds.name}"]
            inputs.append(DatasetInput(id=f"{f.filename}#{ds.name}", name=ds.name, table_kind=ds.table_kind,
                                       granularity=ds.granularity, transposed=ds.transposed, rows=ds.rows,
                                       mapping=[m.model_dump() for m in mapping]))
    return build_context(inputs, s.facts, s.profile)
