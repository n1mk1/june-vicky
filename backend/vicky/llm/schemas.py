"""Structured outputs the agents return (TRD §5.2). Parsed with `messages.parse()`.

Range limits (0–1 confidences, 0–5 scores) are clamped in code after parsing: structured outputs
don't enforce numeric bounds, and code is the authority on every number anyway. None of these
fields carries a figure the product shows as fact: memo evidence is figure *ids*, claims are what
the founder said (checked by `check_claim`), facts must be found verbatim on the cited page.
"""

from typing import Literal

from pydantic import BaseModel, Field

Lens = Literal["claims", "forecast", "retention", "unit_economics", "concentration", "runway", "governance", "market",
               "team", "product_tech", "terms_cap_table", "impact"]
Intent = Literal["follow_up", "new_topic", "jump_in", "pass"]


# ---------------------------------------------------------------- VC memo

class MemoHypothesis(BaseModel):
    attack_id: str | None = Field(description="id of the attack-list item this doubt comes from, or null for a new one")
    claim: str = Field(description="the doubt in one short sentence, no numbers")
    lens: Lens
    evidence: list[str] = Field(description="figure ids (from get_metric / list_metrics / kit tools) behind the doubt")
    severity: float = Field(description="0-1: how much it matters to the investment case")
    confidence: float = Field(description="0-1: how sure you are the doubt is real")


class Memo(BaseModel):
    thesis: str = Field(description="two sentences: how you read the company through your lens")
    hypotheses: list[MemoHypothesis] = Field(description="up to four doubts, most important first")
    mind_changers: list[str] = Field(description="what evidence would change your mind")
    opening_question: str = Field(description="your first question, in your voice; quote figures only as tools gave them")


# ---------------------------------------------------------------- beliefs and bids

class BeliefDelta(BaseModel):
    hyp_id: str
    new_confidence: float
    why: str


class BeliefUpdate(BaseModel):
    deltas: list[BeliefDelta]
    bid: float = Field(description="0-1: how much you want the next question")
    intent: Intent
    target_hyp: str | None = Field(description="the hypothesis id you would ask about, null when passing")


# ---------------------------------------------------------------- chair

class ChairDecision(BaseModel):
    action: Literal["call_on", "interject", "end_session"]
    vc_id: str | None
    intent: Intent | None
    hypothesis_id: str | None
    note: str | None


# ---------------------------------------------------------------- claims

class Claim(BaseModel):
    text: str = Field(description="the founder's exact words that make the claim")
    metric: str = Field(description="metric name, e.g. arr, mrr, growth, churn, nrr, gross margin, burn, runway")
    value: float = Field(description="the number as said; percentages as written (12 for 12%)")
    unit: Literal["money", "pct", "months", "count", "x"]
    period: str | None
    is_forecast: bool


class ClaimList(BaseModel):
    claims: list[Claim]


# ---------------------------------------------------------------- judge

class JudgeScore(BaseModel):
    evidence: float = Field(description="0-5")
    clarity: float = Field(description="0-5")
    composure: float = Field(description="0-5")
    investor_fit: float = Field(description="0-5")
    good: str = Field(description="what to keep, one sentence")
    missing: str = Field(description="what was missing, one sentence")
    strong_answer: str = Field(description="a stronger answer in the founder's voice, using only the figures given")


# ---------------------------------------------------------------- column mapper

class MappedColumn(BaseModel):
    source_column: str
    canonical_field: str | None = Field(description="a target id from the list, or null to keep the column raw")
    unit: str
    confidence: float
    note: str


class ColumnMappingList(BaseModel):
    columns: list[MappedColumn]


# ---------------------------------------------------------------- document facts (FR-7)

class DocFact(BaseModel):
    name: str = Field(description="snake_case metric name, e.g. arr, cash_balance, customers, headcount, burn")
    label: str
    value: float = Field(description="the number exactly as printed; percentages as printed (12 for 12%)")
    unit: Literal["money", "pct", "months", "count", "x", "ratio"]
    currency: str | None = Field(description="ISO code when unit is money (CAD, USD, ...), else null")
    period: str | None = Field(description="the period the number covers, e.g. 2025-12 or FY2025, or null")
    kind: Literal["historical", "forecast"]
    page: int | None = Field(description="1-based page number from the citation; null for non-PDF documents")
    cited_text: str = Field(description="the cited passage, copied exactly from the citation")


class DocFactList(BaseModel):
    facts: list[DocFact]
