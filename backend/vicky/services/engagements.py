"""Engagement lifecycle: profile → uploads → datasets + mappings → facts → confirm.

One engagement is one company. Exactly one is `active` (the confirmed source of truth every
tab reads); confirming another archives the previous one, which stays under Reports.
Everything numeric is recomputed by code from the stored datasets and facts.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import yaml

from vicky import db
from vicky.model.canonical import FIELDS, SPECIAL_TARGETS
from vicky.model.context import TruthContext, build_context
from vicky.model.coverage import coverage
from vicky.model.figures import Fact, Source, figure_dict
from vicky.model.financials import DatasetInput
from vicky.model.loader import ParsedDataset, parse_upload
from vicky.model.mapping import ColumnMapping, propose_heuristic
from vicky.model.truth import check_claim
from vicky.samples import SAMPLES_DIR, load_sample

STAGES = {"pre_seed", "seed", "series_a", "series_b_plus", "other"}
UPLOAD_KINDS = {".csv": "csv", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pdf": "pdf", ".docx": "docx", ".md": "md", ".txt": "md"}
PROFILE_COLUMNS = ("name", "country", "currency", "fiscal_year_start_month", "stage", "round_type", "round_size",
                   "business_model", "granularity")


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


# ---------------------------------------------------------------- profile

def clean_profile(p: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "name" in p:
        out["name"] = str(p["name"] or "").strip()[:200]
    if p.get("country"):
        c = str(p["country"]).strip().upper()[:2]
        out["country"] = "GB" if c == "UK" else c
    if p.get("currency"):
        out["currency"] = str(p["currency"]).strip().upper()[:3]
    if p.get("fiscal_year_start_month") is not None:
        out["fiscal_year_start_month"] = min(12, max(1, int(p["fiscal_year_start_month"])))
    if p.get("stage"):
        s = str(p["stage"]).strip().lower().replace("-", "_").replace(" ", "_")
        out["stage"] = s if s in STAGES else "other"
    if "round_type" in p:
        out["round_type"] = (str(p["round_type"]).strip() or None) if p["round_type"] is not None else None
    if "round_size" in p:
        out["round_size"] = float(p["round_size"]) if p["round_size"] not in (None, "") else None
    if p.get("business_model"):
        out["business_model"] = "recurring" if str(p["business_model"]).lower() == "recurring" else "other"
    if p.get("granularity"):
        out["granularity"] = "quarter" if str(p["granularity"]).lower().startswith("q") else "month"
    extra = {k: v for k, v in p.items() if k in ("one_liner", "city") and v}
    if extra:
        out["extra"] = extra
    return out


async def _upsert_profile(conn, engagement_id: str, profile: dict[str, Any]) -> None:
    p = clean_profile(profile)
    if not p:
        return
    extra = p.pop("extra", None)
    await conn.execute("insert into company_profiles (engagement_id) values ($1) on conflict do nothing", engagement_id)
    sets, args = [], [engagement_id]
    for k, v in p.items():
        args.append(v)
        cast = "::company_stage" if k == "stage" else "::business_model" if k == "business_model" else \
            "::period_granularity" if k == "granularity" else ""
        sets.append(f"{k} = ${len(args)}{cast}")
    if extra:
        args.append(extra)
        sets.append(f"extra = extra || ${len(args)}::jsonb")
    if sets:
        await conn.execute(f"update company_profiles set {', '.join(sets)} where engagement_id = $1", *args)
    if "name" in p:
        await conn.execute("update engagements set name = $2 where id = $1", engagement_id, p["name"])


def _profile_out(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = {k: row.get(k) for k in PROFILE_COLUMNS}
    out["round_size"] = float(row["round_size"]) if row.get("round_size") is not None else None
    out.update(row.get("extra") or {})
    return out


def model_profile(profile: dict | None) -> dict:
    """The profile as the metrics engine expects it (lowercase currency)."""
    p = dict(profile or {})
    p["currency"] = str(p.get("currency") or "usd").lower()
    return p


# ---------------------------------------------------------------- create / load

async def create_engagement(profile: dict[str, Any] | None = None) -> str:
    async with db.pool().acquire() as conn, conn.transaction():
        eid = await conn.fetchval("insert into engagements (name) values ($1) returning id::text",
                                  str((profile or {}).get("name") or "").strip())
        await conn.execute("insert into company_profiles (engagement_id) values ($1)", eid)
        await _upsert_profile(conn, eid, profile or {})
        await conn.execute("insert into truthpacks (engagement_id) values ($1)", eid)
    return eid


async def update_profile(engagement_id: str, profile: dict[str, Any]) -> None:
    await _require(engagement_id)
    async with db.pool().acquire() as conn, conn.transaction():
        await _upsert_profile(conn, engagement_id, profile)
        await _bump(conn, engagement_id)


async def _require(engagement_id: str) -> dict:
    try:
        uuid.UUID(str(engagement_id))
    except ValueError as e:
        raise NotFound("engagement") from e
    row = await db.fetchrow("select * from engagements where id = $1", engagement_id)
    if row is None:
        raise NotFound("engagement")
    return row


async def _pack(conn, engagement_id: str) -> dict:
    row = await conn.fetchrow("select * from truthpacks where engagement_id = $1 order by created_at desc limit 1",
                              engagement_id)
    if row is None:
        tid = await conn.fetchval("insert into truthpacks (engagement_id) values ($1) returning id", engagement_id)
        row = await conn.fetchrow("select * from truthpacks where id = $1", tid)
    return dict(row)


async def _bump(conn, engagement_id: str) -> None:
    await conn.execute("update truthpacks set version = version + 1 where id = "
                       "(select id from truthpacks where engagement_id = $1 order by created_at desc limit 1)", engagement_id)


def _upload_kind(filename: str) -> str:
    for suffix, kind in UPLOAD_KINDS.items():
        if filename.lower().endswith(suffix):
            return kind
    raise Invalid(f"Unsupported file type: {filename}. Use CSV, XLSX, PDF, DOCX or MD.")


async def _store_datasets(conn, engagement_id: str, upload_id: str, kind: str, parsed: list[ParsedDataset],
                          currency: str, preset: dict[str, list[ColumnMapping]] | None = None,
                          filename: str = "") -> None:
    for ds in parsed:
        dsid = await conn.fetchval(
            """insert into datasets (engagement_id, upload_id, name, period_axis, granularity, table_kind, columns, rows,
                 fingerprint, transposed, notes, upload_kind)
               values ($1,$2,$3,$4,$5::period_granularity,$6,$7,$8,$9,$10,$11,$12) returning id::text""",
            engagement_id, upload_id, ds.name, ds.period_axis,
            ds.granularity if ds.granularity in ("month", "quarter", "year") else "none", ds.table_kind,
            [c.as_dict() for c in ds.columns], ds.rows, ds.fingerprint, ds.transposed, ds.notes, kind)
        proposed = (preset or {}).get(f"{filename}#{ds.name}")
        proposer = "sample" if proposed else "heuristic"
        if proposed is None:
            reuse = await conn.fetchval(
                "select confirmed from dataset_mappings where fingerprint = $1 and confirmed is not null "
                "order by confirmed_at desc limit 1", ds.fingerprint)
            if reuse:
                proposed, proposer = [ColumnMapping.model_validate(m) for m in reuse], "reused"
            else:
                proposed = propose_heuristic(ds, currency)
        await conn.execute(
            "insert into dataset_mappings (dataset_id, fingerprint, proposed, proposer) values ($1,$2,$3,$4)",
            dsid, ds.fingerprint, [m.model_dump() for m in proposed], proposer)


async def add_upload(engagement_id: str | None, filename: str, data: bytes, mime: str = "") -> str:
    kind = _upload_kind(filename)
    parsed: list[ParsedDataset] = []
    if kind in ("csv", "xlsx"):
        try:
            parsed = parse_upload(data, filename)
        except Exception as e:  # malformed spreadsheet: keep the bytes, report the error
            raise Invalid(f"Could not read {filename}: {e}") from e
        if not parsed:
            raise Invalid(f"{filename} has no table with a header row")
    if engagement_id is None:
        # Prefill what the file itself shows; the founder confirms the rest in the profile step.
        grans = [d.granularity for d in parsed if d.table_kind == "series" and d.granularity in ("month", "quarter")]
        inferred = {"granularity": grans[0]} if grans else {}
        engagement_id = await create_engagement(inferred)
        if inferred:
            await db.execute("update company_profiles set inferred = $2 where engagement_id = $1", engagement_id,
                             {"granularity": "from the uploaded file"})
    else:
        await _require(engagement_id)
    async with db.pool().acquire() as conn, conn.transaction():
        prof = await conn.fetchrow("select currency from company_profiles where engagement_id = $1", engagement_id)
        uid = await conn.fetchval(
            """insert into uploads (engagement_id, filename, mime, bytes, size, sha256, kind, status)
               values ($1,$2,$3,$4,$5,$6,$7::upload_kind,$8::upload_status) returning id::text""",
            engagement_id, filename, mime or "application/octet-stream", data, len(data), hashlib.sha256(data).hexdigest(),
            kind, "parsed" if parsed else "stored")
        await _store_datasets(conn, engagement_id, uid, kind, parsed, (prof or {}).get("currency", "USD").lower())
        await _bump(conn, engagement_id)
    return engagement_id


async def load_sample_engagement(sample_id: str) -> str:
    if not (SAMPLES_DIR / sample_id / "profile.yaml").exists():
        raise NotFound("sample")
    s = load_sample(sample_id)
    eid = await create_engagement(s.profile)
    deck = []
    deck_path = SAMPLES_DIR / sample_id / "deck_claims.yaml"
    if deck_path.exists():
        raw = yaml.safe_load(deck_path.read_text(encoding="utf-8")) or {}
        deck = raw.get("claims", []) if isinstance(raw, dict) else raw
    async with db.pool().acquire() as conn, conn.transaction():
        for f in s.files:
            kind = _upload_kind(f.filename)
            uid = await conn.fetchval(
                """insert into uploads (engagement_id, filename, mime, bytes, size, sha256, kind, status)
                   values ($1,$2,'text/csv',$3,$4,$5,$6::upload_kind,'parsed') returning id::text""",
                eid, f.filename, f.data, len(f.data), hashlib.sha256(f.data).hexdigest(), kind)
            await _store_datasets(conn, eid, uid, kind, f.datasets, str(s.profile.get("currency", "usd")).lower(),
                                  preset=s.mappings, filename=f.filename)
        facts = [f.model_copy(update={"status": "pending"}) for f in s.facts]
        await conn.execute("update truthpacks set facts = $2, deck_claims = $3 where engagement_id = $1",
                           eid, [f.model_dump(mode="json") for f in facts], deck)
    return eid


# ---------------------------------------------------------------- mappings

def mapping_targets() -> list[dict]:
    out = [{"id": f.id, "label": f.label, "group": f.group} for f in FIELDS.values()]
    labels = {"period": "Period (date axis)", "dim.customer": "Customer name", "dim.cohort": "Signup cohort",
              "value.mrr": "MRR value"}
    out += [{"id": t, "label": labels.get(t, t), "group": "structure"} for t in sorted(SPECIAL_TARGETS)]
    return out


async def get_mapping(dataset_id: str) -> dict:
    try:
        uuid.UUID(dataset_id)
    except ValueError as e:
        raise NotFound("dataset") from e
    row = await db.fetchrow(
        """select d.*, m.proposed, m.confirmed, m.confirmed_at, m.proposer from datasets d
           left join dataset_mappings m on m.dataset_id = d.id where d.id = $1""", dataset_id)
    if row is None:
        raise NotFound("dataset")
    return {"dataset": _dataset_summary(row), "proposed": row["proposed"] or [], "confirmed": row["confirmed"],
            "proposer": row["proposer"], "targets": mapping_targets()}


async def put_mapping(dataset_id: str, mapping: list[dict]) -> dict:
    current = await get_mapping(dataset_id)
    valid = {t["id"] for t in current["targets"]}
    cols = {c["name"] for c in current["dataset"]["columns"]}
    cleaned = []
    for m in mapping:
        cm = ColumnMapping.model_validate(m)
        if cm.source_column not in cols:
            raise Invalid(f"Unknown column {cm.source_column!r}")
        if cm.canonical_field is not None and cm.canonical_field not in valid:
            raise Invalid(f"Unknown canonical field {cm.canonical_field!r}")
        cleaned.append(cm.model_dump())
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("update dataset_mappings set confirmed = $2, confirmed_at = now() where dataset_id = $1",
                           dataset_id, cleaned)
        eid = await conn.fetchval("select engagement_id::text from datasets where id = $1", dataset_id)
        await _bump(conn, eid)
    return await get_mapping(dataset_id)


def _dataset_summary(row: dict) -> dict:
    mapping = row.get("confirmed") or row.get("proposed") or []
    return {"id": str(row["id"]), "upload_id": str(row["upload_id"]) if row.get("upload_id") else None,
            "name": row["name"], "table_kind": row["table_kind"], "granularity": row["granularity"],
            "period_axis": row["period_axis"], "transposed": row.get("transposed", False), "columns": row["columns"],
            "notes": row.get("notes") or [], "mapping_confirmed": row.get("confirmed") is not None,
            "mapped": sum(1 for m in mapping if m.get("canonical_field")), "total": len(row["columns"])}


# ---------------------------------------------------------------- facts

async def add_fact(engagement_id: str, body: dict) -> None:
    await _require(engagement_id)
    try:
        value = float(body["value"])
    except (KeyError, TypeError, ValueError) as e:
        raise Invalid("A fact needs a numeric value") from e
    name = str(body.get("name") or "").strip().lower().replace(" ", "_")
    if not name:
        raise Invalid("A fact needs a name")
    fact = Fact(id=f"typed-{uuid.uuid4().hex[:8]}", name=name, label=str(body.get("label") or name)[:120], value=value,
                unit=str(body.get("unit") or "count").lower(), period=body.get("period") or None,
                kind=body.get("kind") if body.get("kind") in ("historical", "forecast") else "historical",
                source=Source(kind="founder_stated", ref=f"typed by the founder, {datetime.now(UTC):%Y-%m-%d}"),
                status="pending", note=body.get("note"))
    async with db.pool().acquire() as conn, conn.transaction():
        pack = await _pack(conn, engagement_id)
        facts = [*pack["facts"], fact.model_dump(mode="json")]
        await conn.execute("update truthpacks set facts = $2, version = version + 1 where id = $1", pack["id"], facts)


async def remove_fact(engagement_id: str, fact_id: str) -> None:
    await _require(engagement_id)
    async with db.pool().acquire() as conn, conn.transaction():
        pack = await _pack(conn, engagement_id)
        facts = [({**f, "status": "removed"} if f["id"] == fact_id else f) for f in pack["facts"]]
        if facts == pack["facts"]:
            raise NotFound("fact")
        await conn.execute("update truthpacks set facts = $2, version = version + 1 where id = $1", pack["id"], facts)


# ---------------------------------------------------------------- context

_CTX: dict[tuple[str, int], TruthContext] = {}


async def _inputs(engagement_id: str, use_proposed: bool = True) -> list[DatasetInput]:
    rows = await db.fetch(
        """select d.*, m.proposed, m.confirmed from datasets d left join dataset_mappings m on m.dataset_id = d.id
           where d.engagement_id = $1 order by d.created_at""", engagement_id)
    out = []
    for r in rows:
        mapping = r["confirmed"] if r["confirmed"] is not None else (r["proposed"] if use_proposed else None)
        if mapping is None:
            continue
        out.append(DatasetInput(id=str(r["id"]), name=r["name"], table_kind=r["table_kind"], granularity=r["granularity"],
                                transposed=r["transposed"], rows=r["rows"], mapping=mapping,
                                upload_kind=r.get("upload_kind") or "csv"))
    return out


def _deck_checks(deck: list[dict], figures: dict) -> list:
    out = []
    for c in deck or []:
        if c.get("value") is None or not c.get("metric"):
            continue
        chk = check_claim(str(c["metric"]), float(c["value"]), str(c.get("unit") or ""), figures,
                          period=c.get("period"), is_forecast=bool(c.get("is_forecast")))
        chk.text = str(c.get("text") or "")
        out.append(chk)
    return out


async def context(engagement_id: str) -> TruthContext:
    """The TruthContext for an engagement at its current TruthPack version (cached per version)."""
    await _require(engagement_id)
    pack = await db.fetchrow("select * from truthpacks where engagement_id = $1 order by created_at desc limit 1",
                             engagement_id)
    version = pack["version"] if pack else 0
    key = (engagement_id, version)
    if key in _CTX:
        return _CTX[key]
    prof = _profile_out(await db.fetchrow("select * from company_profiles where engagement_id = $1", engagement_id))
    profile = model_profile(prof)
    facts = [Fact.model_validate(f) for f in (pack["facts"] if pack else [])]
    if pack and pack["confirmed_at"] is not None:
        # Once confirmed, only confirmed facts count; a fact typed afterwards waits for re-confirmation.
        facts = [f for f in facts if f.status == "confirmed"]
    inputs = await _inputs(engagement_id)
    base = build_context(inputs, facts, profile, version=version, engagement_id=engagement_id,
                         truthpack_id=str(pack["id"]) if pack else None)
    deck = _deck_checks(pack["deck_claims"] if pack else [], base.figures)
    ctx = build_context(inputs, facts, profile, version=version, engagement_id=engagement_id,
                        truthpack_id=str(pack["id"]) if pack else None, deck_checks=deck) if deck else base
    for k in [k for k in _CTX if k[0] == engagement_id]:
        _CTX.pop(k, None)
    _CTX[key] = ctx
    return ctx


# ---------------------------------------------------------------- confirm

async def confirm(engagement_id: str) -> None:
    from vicky.services import dashboards  # local import: dashboards imports this module

    eng = await _require(engagement_id)
    datasets = await db.fetch("select d.id from datasets d where d.engagement_id = $1", engagement_id)
    async with db.pool().acquire() as conn, conn.transaction():
        pack = await _pack(conn, engagement_id)
        if not datasets and not [f for f in pack["facts"] if f.get("status") != "removed"]:
            raise Invalid("Add a file, a sample or at least one figure before confirming")
        # Unconfirmed proposals are accepted as shown in the confirm step.
        await conn.execute(
            """update dataset_mappings set confirmed = proposed, confirmed_at = now()
               where confirmed is null and dataset_id in (select id from datasets where engagement_id = $1)""",
            engagement_id)
        facts = [({**f, "status": "confirmed"} if f.get("status") == "pending" else f) for f in pack["facts"]]
        await conn.execute("update truthpacks set facts = $2, version = version + 1 where id = $1", pack["id"], facts)
    ctx = await context(engagement_id)
    figures = [figure_dict(f) for f in ctx.figures.values()]
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute(
            """update truthpacks set figures = $2, coverage = $3, attack_list = $4, confirmed_at = now()
               where id = $1""",
            ctx.truthpack_id, figures, coverage(ctx.figures), [a.model_dump() for a in ctx.attack])
        await conn.execute(
            "update engagements set status = 'archived', archived_at = now() where status = 'active' and id <> $1",
            engagement_id)
        await conn.execute(
            "update engagements set status = 'active', confirmed_at = now(), truthpack_id = $2, name = coalesce("
            "nullif((select name from company_profiles where engagement_id = $1), ''), name) where id = $1",
            engagement_id, ctx.truthpack_id)
    _ = eng
    await dashboards.ensure_default(engagement_id, ctx)


# ---------------------------------------------------------------- reads

async def active_id() -> str | None:
    return await db.fetchval("select id::text from engagements where status = 'active' limit 1")


async def resolve(engagement_id: str | None) -> str:
    eid = engagement_id or await active_id()
    if eid is None:
        raise NotFound("No confirmed source of truth yet. Load a sample or upload your data first.")
    return eid


async def detail(engagement_id: str, full: bool = True) -> dict:
    e = await _require(engagement_id)
    prof = _profile_out(await db.fetchrow("select * from company_profiles where engagement_id = $1", engagement_id))
    pack = await db.fetchrow("select id, version, confirmed_at, facts from truthpacks where engagement_id = $1 "
                             "order by created_at desc limit 1", engagement_id)
    out = {"id": str(e["id"]), "name": e["name"] or (prof or {}).get("name") or "Untitled company",
           "status": e["status"], "created_at": e["created_at"], "confirmed_at": e["confirmed_at"], "profile": prof,
           "truthpack": {"id": str(pack["id"]), "version": pack["version"], "confirmed_at": pack["confirmed_at"]} if pack else None}
    if not full:
        return out
    uploads = await db.fetch("select id::text, filename, kind::text, status::text, size from uploads "
                             "where engagement_id = $1 order by created_at", engagement_id)
    ds = await db.fetch(
        """select d.*, m.proposed, m.confirmed from datasets d left join dataset_mappings m on m.dataset_id = d.id
           where d.engagement_id = $1 order by d.created_at""", engagement_id)
    ctx = await context(engagement_id)
    out.update(uploads=uploads, datasets=[_dataset_summary(r) for r in ds],
               facts=[f for f in (pack["facts"] if pack else []) if f.get("status") != "removed"],
               coverage=coverage(ctx.figures))
    return out


async def list_engagements() -> list[dict]:
    rows = await db.fetch("select id::text from engagements order by created_at desc limit 50")
    return [await detail(r["id"], full=False) for r in rows]


async def truth(engagement_id: str) -> dict:
    ctx = await context(engagement_id)
    pack = await db.fetchrow("select * from truthpacks where engagement_id = $1 order by created_at desc limit 1",
                             engagement_id)
    prof = _profile_out(await db.fetchrow("select * from company_profiles where engagement_id = $1", engagement_id))
    return {"engagement_id": engagement_id, "truthpack_id": str(pack["id"]) if pack else None,
            "version": ctx.version, "confirmed_at": pack["confirmed_at"] if pack else None, "company": ctx.company,
            "profile": prof, "figures": [figure_dict(f) for f in ctx.figures.values()],
            "coverage": coverage(ctx.figures), "attack_list": [a.model_dump() for a in ctx.attack],
            "facts": [f.model_dump(mode="json") for f in ctx.facts if f.status != "removed"]}


async def require_confirmed(engagement_id: str | None = None) -> str:
    eid = await resolve(engagement_id)
    ok = await db.fetchval("select confirmed_at is not null from truthpacks where engagement_id = $1 "
                           "order by created_at desc limit 1", eid)
    if not ok:
        raise NotFound("Confirm the source of truth first.")
    return eid
