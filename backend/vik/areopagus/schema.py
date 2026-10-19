"""VCPersona: the spec every investor in the Areopagus is built from (built-in or custom).

Persona text is character description, never instructions: it is placed inside a delimited
block in prompts, and field lengths are capped here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vik.model.canonical import LENSES

LENS_LABELS = {
    "claims": "Deck claims vs the data",
    "forecast": "Growth and the forecast",
    "retention": "Retention and churn",
    "unit_economics": "Unit economics",
    "concentration": "Customer concentration",
    "runway": "Cash and runway",
    "governance": "Governance and mandate",
    "market": "Market size",
    "team": "Team and execution",
    "product_tech": "Product and technology",
    "terms_cap_table": "Terms and cap table",
    "impact": "Impact",
}


class Style(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tone: str = Field(default="neutral", max_length=40)
    interrupt_tendency: float = Field(default=0.4, ge=0, le=1)
    follow_up_depth: int = Field(default=2, ge=1, le=3)
    aggression: float = Field(default=0.4, ge=0, le=1)


class Exchange(BaseModel):
    founder: str = Field(max_length=400)
    vc: str = Field(max_length=600)


class ScoringWeights(BaseModel):
    accuracy: float = 0.2
    evidence: float = 0.2
    clarity: float = 0.2
    composure: float = 0.2
    investor_fit: float = 0.2


class VCPersona(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=40)
    firm: str = Field(default="", max_length=80)
    archetype: str = Field(default="custom", max_length=60)
    glyph: str = Field(default="custom", max_length=20)
    bio: str = Field(default="", max_length=1200)
    cheque_role: str = Field(default="follows", max_length=40)
    priorities: dict[str, float] = Field(default_factory=dict)
    style: Style = Field(default_factory=Style)
    signature_move: str = Field(default="", max_length=120)
    method: str = Field(default="", max_length=2000)
    question_seeds: list[str] = Field(default_factory=list, max_length=20)
    example_exchanges: list[Exchange] = Field(default_factory=list, max_length=8)
    dealbreakers: list[str] = Field(default_factory=list, max_length=10)
    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    voice_id: str | None = None
    kits: list[str] = Field(default_factory=list, max_length=8)
    base_archetype: str | None = None
    builtin: bool = False
    version: int = 1

    @field_validator("priorities")
    @classmethod
    def _lenses(cls, v: dict[str, float]) -> dict[str, float]:
        out = {}
        for lens, w in v.items():
            if lens not in LENSES:
                raise ValueError(f"unknown lens {lens!r}; use one of {', '.join(LENSES)}")
            out[lens] = max(0.0, min(1.0, float(w)))
        return out

    @field_validator("question_seeds", "dealbreakers")
    @classmethod
    def _caps(cls, v: list[str]) -> list[str]:
        return [str(s)[:300] for s in v]

    def weight(self, lens: str) -> float:
        return float(self.priorities.get(lens, 0.0))

    def top_lenses(self, n: int = 3) -> list[str]:
        return [k for k, _ in sorted(self.priorities.items(), key=lambda kv: -kv[1])[:n]]

    def lens_line(self) -> str:
        return ", ".join(LENS_LABELS.get(lens, lens) for lens in self.top_lenses(2))

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "firm": self.firm,
            "archetype": self.archetype,
            "glyph": self.glyph,
            "bio": self.bio,
            "lens": self.lens_line(),
            "signature_move": self.signature_move,
            "priorities": self.priorities,
            "style": self.style.model_dump(),
            "kits": self.kits,
            "builtin": self.builtin,
            "base_archetype": self.base_archetype,
            "version": self.version,
            "cheque_role": self.cheque_role,
        }


PersonaKind = Literal["builtin", "custom", "template"]
