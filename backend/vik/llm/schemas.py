"""Structured outputs the agents return (TRD §5.2). Gemini is asked for JSON constrained to each model's
schema, and the reply is validated with the model (`llm.client.LLM.parse`).

Range limits (0–1 confidences, 0–5 scores) are clamped in code after parsing: structured outputs
don't enforce numeric bounds, and code is the authority on every number anyway. None of these
fields carries a figure the product shows as fact: memo evidence is figure *ids*, claims are what
the founder said (checked by `check_claim`), facts must be found verbatim on the cited page.
"""

from typing import Literal

from pydantic import BaseModel, Field

Lens = Literal[
    "claims",
    "forecast",
    "retention",
    "unit_economics",
    "concentration",
    "runway",
    "governance",
    "market",
    "team",
    "product_tech",
    "terms_cap_table",
    "impact",
]
Intent = Literal["follow_up", "new_topic", "jump_in", "pass"]


# ---------------------------------------------------------------- VC memo


class MemoHypothesis(BaseModel):
    attack_id: str | None = Field(
        description="id of the attack-list item this doubt comes from, or null for a new one"
    )
    claim: str = Field(description="the doubt in one short sentence, no numbers")
    lens: Lens
    evidence: list[str] = Field(
        description="figure ids (from get_metric / list_metrics / kit tools) behind the doubt"
    )
    severity: float = Field(description="0-1: how much it matters to the investment case")
    confidence: float = Field(description="0-1: how sure you are the doubt is real")


class Memo(BaseModel):
    thesis: str = Field(description="two sentences: how you read the company through your lens")
    hypotheses: list[MemoHypothesis] = Field(description="up to four doubts, most important first")
    mind_changers: list[str] = Field(description="what evidence would change your mind")
    opening_question: str = Field(
        description="your first question, in your voice; quote figures only as tools gave them"
    )


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
    intent: Literal["follow_up", "new_topic", "jump_in", "pass", "knowledge"] | None
    hypothesis_id: str | None = Field(
        description="the candidate's hypothesis id, or its probe id for a knowledge check"
    )
    note: str | None


class LineReview(BaseModel):
    """Vik's review of an investor's drafted line, before it is spoken."""

    verdict: Literal["approve", "revise"]
    issues: list[str] = Field(description="short phrases naming what is wrong; empty when approved")
    note: str = Field(description="one sentence to the investor on how to fix the line; empty when approved")


# ---------------------------------------------------------------- knowledge checks


class ProbeDraft(BaseModel):
    vc_id: str = Field(description="the investor who will ask it")
    passage_id: str = Field(description="id of the passage the question is written from")
    question: str = Field(
        description="one question, no numbers, that the founder can answer only if they know the passage"
    )
    answer_quote: str = Field(description="the span of the passage that answers it, copied word for word")


class ProbeList(BaseModel):
    probes: list[ProbeDraft]


class KnowledgeVerdict(BaseModel):
    verdict: Literal["knows", "partial", "contradicts", "missed"]
    explanation: str = Field(
        description="one or two sentences to the founder; quote the note word for word in double "
        "quotes followed by its [kb:path] token"
    )


# ---------------------------------------------------------------- claims


class Claim(BaseModel):
    text: str = Field(description="the founder's exact words that make the claim")
    metric: str = Field(
        description="metric name, e.g. arr, mrr, growth, churn, nrr, gross margin, burn, runway"
    )
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
    strong_answer: str = Field(
        description="a stronger answer in the founder's voice, using only the figures given"
    )


# ---------------------------------------------------------------- Ask Vik (with knowledge-base tools)


class QAReply(BaseModel):
    reply: str = Field(
        description="the answer: at most four short sentences of plain prose; note quotes keep "
        "their [kb:path] token"
    )


class RagReply(BaseModel):
    """Ask Vik from retrieved passages (docs/08-RAG.md). Every sentence of `reply` carries a citation."""

    answerable: bool = Field(
        description="false when the data and the passages given don't answer the question"
    )
    reply: str = Field(
        description="at most four short sentences; each one states a figure from <data> exactly "
        "or quotes a passage word for word in double quotes followed by its [kb:path]"
    )


# ---------------------------------------------------------------- column mapper


class MappedColumn(BaseModel):
    source_column: str
    canonical_field: str | None = Field(
        description="a target id from the list, or null to keep the column raw"
    )
    unit: str
    confidence: float
    note: str


class ColumnMappingList(BaseModel):
    columns: list[MappedColumn]


# ---------------------------------------------------------------- document facts (FR-7)


class DocFact(BaseModel):
    name: str = Field(
        description="snake_case metric name, e.g. arr, cash_balance, customers, headcount, burn"
    )
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


# ---------------------------------------------------------------- Areopagus builder (FR-13)


class LensWeight(BaseModel):
    lens: Lens
    weight: float = Field(description="0-1: how hard this investor presses on the lens")


class PersonaDraft(BaseModel):
    """A custom investor drafted from a founder's description. Code clamps every range and caps
    every list before it becomes a `VCPersona`; nothing here is a figure about the company."""

    name: str = Field(description="first name only, as the description gives it, or a plausible one")
    firm: str = Field(
        description="fund or role label, e.g. 'Seed fund' or 'Angel operator'; no real firm names"
    )
    archetype: str = Field(description="snake_case archetype, e.g. nrr_obsessed_saas_partner")
    cheque_role: str = Field(description="one of the cheque roles listed")
    bio: str = Field(
        description="two or three sentences: who they are, what they optimise for, how they come across"
    )
    priorities: list[LensWeight] = Field(
        description="a weight for every lens; the lenses the description stresses high"
    )
    tone: str = Field(description="snake_case tone, e.g. blunt or warm_rigorous")
    interrupt_tendency: float = Field(description="0-1")
    follow_up_depth: int = Field(description="1-3: how many follow-ups before moving on")
    aggression: float = Field(description="0-1")
    signature_move: str = Field(description="their signature move in under eight words")
    method: str = Field(description="how they run a pitch meeting, three or four sentences")
    question_seeds: list[str] = Field(description="four to six questions in their voice, no numbers")
    dealbreakers: list[str] = Field(description="two to four things that end their interest")
