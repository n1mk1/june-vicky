"""Test helpers: build the canonical model and metrics for a sample without a database, or load a
sample into the database as a draft engagement (the app itself never offers samples)."""

import hashlib

import yaml

from vik import db
from vik.model.financials import DatasetInput, build_model
from vik.model.metrics import compute_metrics
from vik.samples import SAMPLES_DIR, load_sample
from vik.services import engagements


def sample_model(sample_id: str):
    s = load_sample(sample_id)
    inputs = []
    for f in s.files:
        for ds in f.datasets:
            mapping = s.mappings[f"{f.filename}#{ds.name}"]
            inputs.append(
                DatasetInput(
                    id=f"{f.filename}#{ds.name}",
                    name=ds.name,
                    table_kind=ds.table_kind,
                    granularity=ds.granularity,
                    transposed=ds.transposed,
                    rows=ds.rows,
                    mapping=[m.model_dump() for m in mapping],
                )
            )
    model = build_model(inputs, s.profile.get("currency", "usd"), s.profile.get("granularity"))
    return s, model


def sample_metrics(sample_id: str):
    s, model = sample_model(sample_id)
    return s, model, compute_metrics(model, s.facts, s.profile)


async def load_sample_engagement(sample_id: str) -> str:
    """Store a sample as a draft engagement: its files as uploads, its mappings proposed, its pack facts pending."""
    s = load_sample(sample_id)
    eid = await engagements.create_engagement(s.profile)
    deck = []
    deck_path = SAMPLES_DIR / sample_id / "deck_claims.yaml"
    if deck_path.exists():
        raw = yaml.safe_load(deck_path.read_text(encoding="utf-8")) or {}
        deck = raw.get("claims", []) if isinstance(raw, dict) else raw
    async with db.pool().acquire() as conn, conn.transaction():
        for f in s.files:
            kind = engagements._upload_kind(f.filename)
            uid = await conn.fetchval(
                """insert into uploads (engagement_id, filename, mime, bytes, size, sha256, kind, status)
                   values ($1,$2,'text/csv',$3,$4,$5,$6::upload_kind,'parsed') returning id::text""",
                eid,
                f.filename,
                f.data,
                len(f.data),
                hashlib.sha256(f.data).hexdigest(),
                kind,
            )
            await engagements._store_datasets(
                conn,
                eid,
                uid,
                kind,
                f.datasets,
                str(s.profile.get("currency", "usd")).lower(),
                preset=s.mappings,
                filename=f.filename,
            )
        facts = [f.model_copy(update={"status": "pending"}) for f in s.facts]
        await conn.execute(
            "update truthpacks set facts = $2, deck_claims = $3 where engagement_id = $1",
            eid,
            [f.model_dump(mode="json") for f in facts],
            deck,
        )
    return eid


async def load_and_confirm(api_client, sample_id: str) -> dict:
    """Load a sample as a draft and confirm it over the API; returns the confirmed engagement."""
    eid = await load_sample_engagement(sample_id)
    r = await api_client.post(f"/engagements/{eid}/confirm")
    assert r.status_code == 200, r.text
    return r.json()


class Started:
    """What starting a court returns, shaped like the API's response (`status_code`, `json()`, `text`)."""

    def __init__(self, status_code: int, body: dict):
        self.status_code, self.body = status_code, body
        self.text = str(body)

    def json(self) -> dict:
        return self.body


async def start_court(
    panel: list[str] | None = None,
    question_cap: int | None = None,
    knowledge: bool = True,
    coaching: str = "coached",
    focus: str | None = None,
) -> Started:
    """Open the court the way Simulation does after a pitch (`pitch.end` → `court.start`), returning its view;
    409 without a confirmed source of truth, 422 for a bad panel."""
    from vik.areopagus.registry import PersonaError
    from vik.court import session as court

    try:
        await engagements.require_confirmed()
    except engagements.NotFound as e:
        return Started(409, {"detail": str(e)})
    try:
        sid = await court.start(panel, question_cap, coaching, focus, knowledge)
    except (PersonaError, court.CourtError) as e:
        return Started(422, {"detail": str(e)})
    return Started(200, await court.view(sid))
