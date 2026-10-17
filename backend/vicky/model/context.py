"""TruthContext: everything code knows about one engagement's confirmed source of truth.

Built once per TruthPack version and passed to metrics consumers, kits, the dashboard
evaluator and agents. Agents never see raw data; they call tools that read from here.
"""

from dataclasses import dataclass, field
from typing import Any

from vicky.model.figures import Fact, Figure, MissingFigure
from vicky.model.financials import CanonicalModel, DatasetInput, build_model
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


def build_context(datasets: list[DatasetInput], facts: list[Fact], profile: dict[str, Any], version: int = 1,
                  truthpack_id: str | None = None, engagement_id: str | None = None,
                  deck_checks: list | None = None) -> TruthContext:
    model = build_model(datasets, profile.get("currency", "usd"), profile.get("granularity"))
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
