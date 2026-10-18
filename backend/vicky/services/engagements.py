"""Engagement lifecycle: profile → uploads → datasets + mappings → facts → confirm.

One engagement is one company. Exactly one is `active` (the confirmed source of truth every
tab reads); confirming another archives the previous one, which stays under Reports.
Everything numeric is recomputed by code from the stored datasets and facts.
"""

import hashlib
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from vicky import db, jobs, llm
from vicky.llm import mapper
from vicky.model import fx as fx_model
from vicky.model.canonical import FIELDS, SPECIAL_KINDS, SPECIAL_TARGETS, STRUCTURE_UNITS
from vicky.model.context import TruthContext, build_context
from vicky.model.coverage import coverage
from vicky.model.currencies import norm_currency
from vicky.model.figures import CURRENCY_UNITS, UNITS, Fact, Source, figure_dict
from vicky.model.financials import DatasetInput, model_notes
from vicky.model.fx import Rates
from vicky.model.loader import ColumnProfile, ParsedDataset, parse_upload
from vicky.model.mapping import ColumnMapping, propose_heuristic, unit_for
from vicky.model.truth import check_claim
from vicky.services import fx

STAGES = {"pre_seed", "seed", "series_a", "series_b_plus", "other"}
UPLOAD_KINDS = {
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "md",
    ".txt": "md",
}
DOC_KINDS = {"pdf", "docx", "md"}
PROFILE_COLUMNS = (
    "name",
    "country",
    "currency",
    "fiscal_year_start_month",
    "stage",
    "round_type",
    "round_size",
    "business_model",
    "granularity",
)
MONEY_ALIASES = {"money", "$"}  # a typed fact in the reporting currency
FACT_UNITS = UNITS | MONEY_ALIASES
ROUND_SIZE_MAX = 1e12  # company_profiles.round_size is numeric(14, 2)
# Below this a proposed mapping is a guess the founder must check (the mapping table marks it in ember).
REVIEW_CONFIDENCE = 0.6


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


# ---------------------------------------------------------------- profile


def _number(p: dict[str, Any], key: str) -> float:
    try:
        v = float(p[key])
    except (TypeError, ValueError) as e:
        raise Invalid(f"{key} must be a number, not {str(p[key])[:40]!r}") from e
    if not math.isfinite(v):
        raise Invalid(f"{key} must be a finite number")
    return v


def clean_profile(p: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(p, dict):
        raise Invalid("The profile must be an object of fields")
    out: dict[str, Any] = {}
    if "name" in p:
        out["name"] = str(p["name"] or "").strip()[:200]
    if p.get("country"):
        c = str(p["country"]).strip().upper()[:2]
        out["country"] = "GB" if c == "UK" else c
    if p.get("currency"):
        out["currency"] = norm_currency(p["currency"]).upper()
    if p.get("fiscal_year_start_month") is not None:
        out["fiscal_year_start_month"] = min(12, max(1, int(_number(p, "fiscal_year_start_month"))))
    if p.get("stage"):
        s = str(p["stage"]).strip().lower().replace("-", "_").replace(" ", "_")
        out["stage"] = s if s in STAGES else "other"
    if "round_type" in p:
        out["round_type"] = (str(p["round_type"]).strip() or None) if p["round_type"] is not None else None
    if "round_size" in p:
        out["round_size"] = _number(p, "round_size") if p["round_size"] not in (None, "") else None
        if out["round_size"] is not None and not 0 <= out["round_size"] < ROUND_SIZE_MAX:
            raise Invalid("round_size must be between 0 and 1,000,000,000,000")
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
    await conn.execute(
        "insert into company_profiles (engagement_id) values ($1) on conflict do nothing", engagement_id
    )
    sets, args = [], [engagement_id]
    for k, v in p.items():
        args.append(v)
        cast = (
            "::company_stage"
            if k == "stage"
            else "::business_model"
            if k == "business_model"
            else "::period_granularity"
            if k == "granularity"
            else ""
        )
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
    p["currency"] = norm_currency(p.get("currency"))
    return p


# ---------------------------------------------------------------- create / load


async def create_engagement(profile: dict[str, Any] | None = None) -> str:
    async with db.acquire() as conn, conn.transaction():
        eid = await conn.fetchval(
            "insert into engagements (name) values ($1) returning id::text",
            str((profile or {}).get("name") or "").strip(),
        )
        await conn.execute("insert into company_profiles (engagement_id) values ($1)", eid)
        await _upsert_profile(conn, eid, profile or {})
        await conn.execute("insert into truthpacks (engagement_id) values ($1)", eid)
    return eid


async def update_profile(engagement_id: str, profile: dict[str, Any]) -> None:
    await _require(engagement_id)
    async with db.acquire() as conn, conn.transaction():
        old = norm_currency(
            await conn.fetchval(
                "select currency from company_profiles where engagement_id = $1", engagement_id
            )
        )
        await _upsert_profile(conn, engagement_id, profile)
        new = norm_currency(
            await conn.fetchval(
                "select currency from company_profiles where engagement_id = $1", engagement_id
            )
        )
        if new != old:
            await _follow_currency(conn, engagement_id, old, new)
        await _bump(conn, engagement_id)


async def _follow_currency(conn, engagement_id: str, old: str, new: str) -> None:
    """Columns that were in the reporting currency move with it when the founder changes it; a column
    set to another currency (read from the file, or chosen in the mapping) keeps its own."""
    rows = await conn.fetch(
        """select m.dataset_id, m.proposed, m.confirmed from dataset_mappings m join datasets d on d.id = m.dataset_id
           where d.engagement_id = $1""",
        engagement_id,
    )
    for r in rows:
        moved = {}
        for col in ("proposed", "confirmed"):
            if r[col] is not None:
                moved[col] = [
                    {**m, "unit": new} if str(m.get("unit") or "").lower() == old else m for m in r[col]
                ]
        await conn.execute(
            "update dataset_mappings set proposed = $2, confirmed = coalesce($3, confirmed) "
            "where dataset_id = $1",
            r["dataset_id"],
            moved.get("proposed", r["proposed"]),
            moved.get("confirmed"),
        )


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
    row = await conn.fetchrow(
        "select * from truthpacks where engagement_id = $1 order by created_at desc limit 1", engagement_id
    )
    if row is None:
        tid = await conn.fetchval(
            "insert into truthpacks (engagement_id) values ($1) returning id", engagement_id
        )
        row = await conn.fetchrow("select * from truthpacks where id = $1", tid)
    return dict(row)


async def _bump(conn, engagement_id: str) -> None:
    await conn.execute(
        "update truthpacks set version = version + 1 where id = "
        "(select id from truthpacks where engagement_id = $1 order by created_at desc limit 1)",
        engagement_id,
    )


def _upload_kind(filename: str) -> str:
    for suffix, kind in UPLOAD_KINDS.items():
        if filename.lower().endswith(suffix):
            return kind
    raise Invalid(f"Unsupported file type: {filename}. Use CSV, XLSX, PDF, DOCX or MD.")


async def _store_datasets(
    conn,
    engagement_id: str,
    upload_id: str,
    kind: str,
    parsed: list[ParsedDataset],
    currency: str,
    preset: dict[str, list[ColumnMapping]] | None = None,
    filename: str = "",
    refined: dict[str, tuple[list[ColumnMapping], str]] | None = None,
) -> None:
    for ds in parsed:
        dsid = await conn.fetchval(
            """insert into datasets (engagement_id, upload_id, name, period_axis, granularity, table_kind, columns, rows,
                 fingerprint, transposed, notes, upload_kind)
               values ($1,$2,$3,$4,$5::period_granularity,$6,$7,$8,$9,$10,$11,$12) returning id::text""",
            engagement_id,
            upload_id,
            ds.name,
            ds.period_axis,
            ds.granularity if ds.granularity in ("month", "quarter", "year") else "none",
            ds.table_kind,
            [c.as_dict() for c in ds.columns],
            ds.rows,
            ds.fingerprint,
            ds.transposed,
            ds.notes,
            kind,
        )
        proposed = (preset or {}).get(f"{filename}#{ds.name}")
        proposer = "sample" if proposed else "heuristic"
        if proposed is None:
            reuse = await conn.fetchval(
                "select confirmed from dataset_mappings where fingerprint = $1 and confirmed is not null "
                "order by confirmed_at desc limit 1",
                ds.fingerprint,
            )
            if reuse:
                proposed, proposer = [ColumnMapping.model_validate(m) for m in reuse], "reused"
            elif refined and ds.name in refined:
                proposed, proposer = refined[ds.name]
            else:
                proposed = propose_heuristic(ds, currency)
        await conn.execute(
            "insert into dataset_mappings (dataset_id, fingerprint, proposed, proposer) values ($1,$2,$3,$4)",
            dsid,
            ds.fingerprint,
            [m.model_dump() for m in proposed],
            proposer,
        )


async def add_upload(
    engagement_id: str | None, filename: str, data: bytes, mime: str = "", kb_note_id: str | None = None
) -> str:
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
        grans = [
            d.granularity
            for d in parsed
            if d.table_kind == "series" and d.granularity in ("month", "quarter")
        ]
        inferred = {"granularity": grans[0]} if grans else {}
        engagement_id = await create_engagement(inferred)
        if inferred:
            await db.execute(
                "update company_profiles set inferred = $2 where engagement_id = $1",
                engagement_id,
                {"granularity": "from the uploaded file"},
            )
    else:
        await _require(engagement_id)
    currency = norm_currency(
        await db.fetchval("select currency from company_profiles where engagement_id = $1", engagement_id)
    )
    # Claude refines the heuristic mapping (when a key is set) before the transaction; a dataset whose
    # fingerprint has a confirmed mapping already reuses it, so it isn't sent.
    refined: dict[str, tuple[list[ColumnMapping], str]] = {}
    if llm.enabled() and parsed:
        fresh = [
            ds
            for ds in parsed
            if not await db.fetchval(
                "select 1 from dataset_mappings where fingerprint = $1 and confirmed is not null limit 1",
                ds.fingerprint,
            )
        ]
        refined = await mapper.propose_all(fresh, currency)
    async with db.acquire() as conn, conn.transaction():
        uid = await conn.fetchval(
            """insert into uploads (engagement_id, filename, mime, bytes, size, sha256, kind, status, kb_note_id)
               values ($1,$2,$3,$4,$5,$6,$7::upload_kind,$8::upload_status,$9::uuid) returning id::text""",
            engagement_id,
            filename,
            mime or "application/octet-stream",
            data,
            len(data),
            hashlib.sha256(data).hexdigest(),
            kind,
            "parsed" if parsed else "stored",
            kb_note_id,
        )
        await _store_datasets(conn, engagement_id, uid, kind, parsed, currency, refined=refined)
        await _bump(conn, engagement_id)
    if llm.enabled() and (kind in DOC_KINDS or any(ds.table_kind == "raw" and ds.rows for ds in parsed)):
        # FR-7: facts with citations from the document, landing as pending in the TruthPack. A table with no
        # date axis (a KPI sheet, a cap table) has no series to map, so its figures are read as facts too.
        await jobs.enqueue("extract", {"upload_id": uid}, engagement_id=engagement_id)
    return engagement_id


async def add_extracted_facts(upload_id: str, facts: list[Fact]) -> int:
    """Append an extract job's facts to the upload's TruthPack as pending (idempotent per fact id)."""
    from vicky.llm.docs import merge_pending

    eid = await db.fetchval("select engagement_id::text from uploads where id::text = $1", upload_id)
    if eid is None:
        raise NotFound("upload")
    async with db.acquire() as conn, conn.transaction():
        pack = await conn.fetchrow(
            "select * from truthpacks where engagement_id = $1 order by created_at desc limit 1 for update",
            eid,
        )
        if pack is None:
            pack = await _pack(conn, eid)
        merged, added = merge_pending(list(pack["facts"] or []), facts)
        if added:
            await conn.execute(
                "update truthpacks set facts = $2, version = version + 1 where id = $1", pack["id"], merged
            )
        await conn.execute("update uploads set status = 'extracted' where id::text = $1", upload_id)
    return added


# ---------------------------------------------------------------- mappings


def mapping_targets() -> list[dict]:
    """Each target with `kind` (money, count, date, text) so the mapping step can set the unit it implies."""
    out = [{"id": f.id, "label": f.label, "group": f.group, "kind": f.kind} for f in FIELDS.values()]
    labels = {
        "period": "Period (date axis)",
        "dim.customer": "Customer name",
        "dim.cohort": "Signup cohort",
        "value.mrr": "MRR value",
    }
    out += [
        {"id": t, "label": labels.get(t, t), "group": "structure", "kind": SPECIAL_KINDS[t]}
        for t in sorted(SPECIAL_TARGETS)
    ]
    return out


async def get_mapping(dataset_id: str) -> dict:
    try:
        uuid.UUID(dataset_id)
    except ValueError as e:
        raise NotFound("dataset") from e
    row = await db.fetchrow(
        """select d.*, m.proposed, m.confirmed, m.confirmed_at, m.proposer from datasets d
           left join dataset_mappings m on m.dataset_id = d.id where d.id = $1""",
        dataset_id,
    )
    if row is None:
        raise NotFound("dataset")
    return {
        "dataset": _dataset_summary(row),
        "proposed": row["proposed"] or [],
        "confirmed": row["confirmed"],
        "proposer": row["proposer"],
        "targets": mapping_targets(),
    }


def _clean_unit(cm: ColumnMapping, col: ColumnProfile | None, currency: str) -> str:
    """The unit the chosen field implies wins over a stale one (a date axis is "date", money a currency, a
    count "count"); a raw column keeps what the founder picked."""
    unit = (cm.unit or "").strip().lower()
    implied = unit_for(cm.canonical_field, currency, col)
    if cm.canonical_field in SPECIAL_KINDS and SPECIAL_KINDS[cm.canonical_field] != "money":
        return implied
    if cm.canonical_field in FIELDS:
        money = FIELDS[cm.canonical_field].kind == "money"
        return unit if (unit in CURRENCY_UNITS if money else unit in UNITS - CURRENCY_UNITS) else implied
    if cm.canonical_field == "value.mrr":
        return unit if unit in CURRENCY_UNITS else implied
    if unit in ("month", "quarter", "year", "day", "week"):
        return "date"
    if unit and unit not in UNITS | STRUCTURE_UNITS:
        raise Invalid(f"Unknown unit {unit!r} for {cm.source_column!r}")
    return unit


async def put_mapping(dataset_id: str, mapping: list[dict]) -> dict:
    current = await get_mapping(dataset_id)
    ds = current["dataset"]
    valid = {t["id"] for t in current["targets"]}
    cols = {c["name"]: c for c in ds["columns"]}
    chosen = [ColumnMapping.model_validate(m) for m in mapping]
    for cm in chosen:
        if cm.source_column not in cols:
            raise Invalid(f"Unknown column {cm.source_column!r}")
        if cm.canonical_field is not None and cm.canonical_field not in valid:
            raise Invalid(f"Unknown canonical field {cm.canonical_field!r}")
    axes = [cm.source_column for cm in chosen if cm.canonical_field == "period"]
    if len(axes) > 1:
        raise Invalid(f"Only one column can be the date axis; {', '.join(axes)} are all set to it.")
    eid = await db.fetchval("select engagement_id::text from datasets where id = $1", dataset_id)
    currency = norm_currency(
        await db.fetchval("select currency from company_profiles where engagement_id = $1", eid)
    )
    moved = bool(axes) and axes[0] not in (ds["period_axis"], "period") and not ds.get("transposed")
    reread = await _reread(ds, axes[0]) if moved else None
    if reread is not None:
        # The founder chose another column as the dates: the table is read again around it.
        cols = {c.name: c.as_dict() for c in reread.columns}
        keep = {cm.source_column: cm for cm in chosen if cm.source_column in cols}
        chosen = [keep.get(p.source_column, p) for p in propose_heuristic(reread, currency)]
    profiles = {
        n: ColumnProfile(
            **{k: c.get(k) for k in ("name", "dtype", "sample_values", "null_rate", "currency")},
            unit_hint=c.get("unit_hint"),
            scale=c.get("scale") or 1.0,
        )
        for n, c in cols.items()
    }
    cleaned = []
    for cm in chosen:
        cm.unit = _clean_unit(cm, profiles.get(cm.source_column), currency)
        cleaned.append(cm.model_dump())
    async with db.acquire() as conn, conn.transaction():
        if reread is not None:
            await conn.execute(
                """update datasets set columns = $2, rows = $3, period_axis = $4, granularity = $5::period_granularity,
                     table_kind = $6, notes = $7, transposed = $8 where id = $1""",
                dataset_id,
                [c.as_dict() for c in reread.columns],
                reread.rows,
                reread.period_axis,
                reread.granularity if reread.granularity in ("month", "quarter", "year") else "none",
                reread.table_kind,
                reread.notes,
                reread.transposed,
            )
        await conn.execute(
            "update dataset_mappings set confirmed = $2, confirmed_at = now() where dataset_id = $1",
            dataset_id,
            cleaned,
        )
        await _bump(conn, eid)
    return await get_mapping(dataset_id)


async def _reread(ds: dict, column: str) -> ParsedDataset:
    """The dataset parsed again from its upload with `column` as the date axis."""
    up = await db.fetchrow("select filename, bytes from uploads where id::text = $1", ds.get("upload_id"))
    if up is None:
        raise Invalid(
            "The file this table came from is gone, so it can't be read again with another date column."
        )
    try:
        parsed = parse_upload(bytes(up["bytes"]), up["filename"], period_column={ds["name"]: column})
    except ValueError as e:
        raise Invalid(str(e)) from e
    match = next((p for p in parsed if p.name == ds["name"]), None)
    if match is None:
        raise Invalid(f"Couldn't find the table {ds['name']!r} in {up['filename']} any more.")
    return match


def _dataset_summary(row: dict) -> dict:
    mapping = row.get("confirmed") or row.get("proposed") or []
    return {
        "id": str(row["id"]),
        "upload_id": str(row["upload_id"]) if row.get("upload_id") else None,
        "name": row["name"],
        "table_kind": row["table_kind"],
        "granularity": row["granularity"],
        "period_axis": row["period_axis"],
        "transposed": row.get("transposed", False),
        "columns": row["columns"],
        "notes": row.get("notes") or [],
        "mapping_confirmed": row.get("confirmed") is not None,
        "mapped": sum(1 for m in mapping if m.get("canonical_field")),
        "total": len(row["columns"]),
    }


# ---------------------------------------------------------------- facts


async def add_fact(engagement_id: str, body: dict) -> None:
    await _require(engagement_id)
    try:
        value = float(body["value"])
    except (KeyError, TypeError, ValueError) as e:
        raise Invalid("A fact needs a numeric value") from e
    if not math.isfinite(value):
        raise Invalid("A fact's value must be a finite number")
    name = str(body.get("name") or "").strip().lower().replace(" ", "_")
    if not name:
        raise Invalid("A fact needs a name")
    unit = str(body.get("unit") or "count").strip().lower()
    if unit in MONEY_ALIASES:  # "$" or "money": the reporting currency, never a count
        unit = norm_currency(
            await db.fetchval("select currency from company_profiles where engagement_id = $1", engagement_id)
        )
    if unit not in UNITS:
        raise Invalid(f"Unknown unit {unit!r}; use a currency code, money, pct, months, count, ratio or x")
    fact = Fact(
        id=f"typed-{uuid.uuid4().hex[:8]}",
        name=name,
        label=str(body.get("label") or name)[:120],
        value=value,
        unit=unit,
        period=body.get("period") or None,
        kind=body.get("kind") if body.get("kind") in ("historical", "forecast") else "historical",
        source=Source(kind="founder_stated", ref=f"typed by the founder, {datetime.now(UTC):%Y-%m-%d}"),
        status="pending",
        note=body.get("note"),
    )
    async with db.acquire() as conn, conn.transaction():
        pack = await _pack(conn, engagement_id)
        facts = [*pack["facts"], fact.model_dump(mode="json")]
        await conn.execute(
            "update truthpacks set facts = $2, version = version + 1 where id = $1", pack["id"], facts
        )


async def remove_fact(engagement_id: str, fact_id: str) -> None:
    await _require(engagement_id)
    async with db.acquire() as conn, conn.transaction():
        pack = await _pack(conn, engagement_id)
        facts = [({**f, "status": "removed"} if f["id"] == fact_id else f) for f in pack["facts"]]
        if facts == pack["facts"]:
            raise NotFound("fact")
        await conn.execute(
            "update truthpacks set facts = $2, version = version + 1 where id = $1", pack["id"], facts
        )


# ---------------------------------------------------------------- context

_CTX: dict[tuple[str, int, str], TruthContext] = {}


async def _inputs(engagement_id: str, use_proposed: bool = True) -> list[DatasetInput]:
    rows = await db.fetch(
        """select d.*, m.proposed, m.confirmed from datasets d left join dataset_mappings m on m.dataset_id = d.id
           where d.engagement_id = $1 order by d.created_at""",
        engagement_id,
    )
    out = []
    for r in rows:
        mapping = r["confirmed"] if r["confirmed"] is not None else (r["proposed"] if use_proposed else None)
        if mapping is None:
            continue
        out.append(
            DatasetInput(
                id=str(r["id"]),
                name=r["name"],
                table_kind=r["table_kind"],
                granularity=r["granularity"],
                transposed=r["transposed"],
                rows=r["rows"],
                mapping=mapping,
                upload_kind=r.get("upload_kind") or "csv",
            )
        )
    return out


def _deck_checks(deck: list[dict], figures: dict) -> list:
    out = []
    for c in deck or []:
        if c.get("value") is None or not c.get("metric"):
            continue
        chk = check_claim(
            str(c["metric"]),
            float(c["value"]),
            str(c.get("unit") or ""),
            figures,
            period=c.get("period"),
            is_forecast=bool(c.get("is_forecast")),
        )
        chk.text = str(c.get("text") or "")
        out.append(chk)
    return out


async def rates_for(
    inputs: list[DatasetInput], facts: list[Fact], profile: dict, target: str
) -> Rates | None:
    """Bank of Canada rates for every currency the data is in that isn't `target`, from its first period."""
    units = (
        [m.get("unit") for d in inputs for m in d.mapping]
        + [f.unit for f in facts]
        + [profile.get("currency"), target]
    )
    codes = fx_model.needed_codes(*units)
    if not codes:
        return None
    periods = [r["period"] for d in inputs for r in d.rows if r.get("period")] + [
        f.period for f in facts if f.period
    ]
    return await fx.load(codes, fx_model.earliest_date(periods))


async def context(engagement_id: str, currency: str | None = None) -> TruthContext:
    """The TruthContext for an engagement at its current TruthPack version, with every money figure in
    `currency` (default: the profile's reporting currency). Cached per version and currency."""
    await _require(engagement_id)
    pack = await db.fetchrow(
        "select * from truthpacks where engagement_id = $1 order by created_at desc limit 1", engagement_id
    )
    version = pack["version"] if pack else 0
    prof = _profile_out(
        await db.fetchrow("select * from company_profiles where engagement_id = $1", engagement_id)
    )
    profile = model_profile(prof)
    target = norm_currency(currency, profile["currency"])
    key = (engagement_id, version, target)
    if key in _CTX:
        return _CTX[key]
    facts = [Fact.model_validate(f) for f in (pack["facts"] if pack else [])]
    if pack and pack["confirmed_at"] is not None:
        # Once confirmed, only confirmed facts count; a fact typed afterwards waits for re-confirmation.
        facts = [f for f in facts if f.status == "confirmed"]
    inputs = await _inputs(engagement_id)
    rates = await rates_for(inputs, facts, profile, target)
    common = {
        "version": version,
        "engagement_id": engagement_id,
        "truthpack_id": str(pack["id"]) if pack else None,
        "fx": rates,
        "currency": target,
    }
    base = build_context(inputs, facts, profile, **common)
    deck = _deck_checks(pack["deck_claims"] if pack else [], base.figures)
    ctx = build_context(inputs, facts, profile, deck_checks=deck, **common) if deck else base
    for k in [k for k in _CTX if k[0] == engagement_id and k[1] != version]:
        _CTX.pop(k, None)
    _CTX[key] = ctx
    return ctx


# ---------------------------------------------------------------- confirm


def needs_review(proposed: list[dict], proposer: str | None) -> list[str]:
    """Columns of an unreviewed proposal that confirm must not take as they are: mapped to a field with
    confidence under REVIEW_CONFIDENCE. A mapping reused from one the founder confirmed before is theirs."""
    if proposer == "reused":
        return []
    return [
        str(m.get("source_column"))
        for m in proposed or []
        if m.get("canonical_field") and float(m.get("confidence") or 0) < REVIEW_CONFIDENCE
    ]


async def confirm(engagement_id: str) -> None:
    from vicky.services import dashboards  # local import: dashboards imports this module

    eng = await _require(engagement_id)
    datasets = await db.fetch("select d.id from datasets d where d.engagement_id = $1", engagement_id)
    async with db.acquire() as conn, conn.transaction():
        pack = await _pack(conn, engagement_id)
        if not datasets and not [f for f in pack["facts"] if f.get("status") != "removed"]:
            raise Invalid("Add a file or at least one figure before confirming")
        unreviewed = await conn.fetch(
            """select d.name, m.proposed, m.proposer from datasets d join dataset_mappings m on m.dataset_id = d.id
               where d.engagement_id = $1 and m.confirmed is null order by d.created_at""",
            engagement_id,
        )
        guesses = [
            f"{', '.join(cols)} ({r['name']})"
            for r in unreviewed
            if (cols := needs_review(r["proposed"], r["proposer"]))
        ]
        if guesses:
            # A low-confidence guess could put a column's numbers on the wrong line of the source of truth.
            raise Invalid(
                f"Check the mapping before confirming. Matched with low confidence: {'; '.join(guesses)}. "
                "Review them in step 2 (Mapping) and save."
            )
        # Unconfirmed proposals the founder didn't change are accepted as shown in the confirm step
        # (none of them is a low-confidence guess: those stop the confirm above).
        await conn.execute(
            """update dataset_mappings set confirmed = proposed, confirmed_at = now()
               where confirmed is null and dataset_id in (select id from datasets where engagement_id = $1)""",
            engagement_id,
        )
        facts = [({**f, "status": "confirmed"} if f.get("status") == "pending" else f) for f in pack["facts"]]
        await conn.execute(
            "update truthpacks set facts = $2, version = version + 1 where id = $1", pack["id"], facts
        )
    ctx = await context(engagement_id)
    figures = [figure_dict(f) for f in ctx.figures.values()]
    async with db.acquire() as conn, conn.transaction():
        await conn.execute(
            """update truthpacks set figures = $2, coverage = $3, attack_list = $4, confirmed_at = now()
               where id = $1""",
            ctx.truthpack_id,
            figures,
            coverage(ctx.figures),
            [a.model_dump() for a in ctx.attack],
        )
        await conn.execute(
            "update engagements set status = 'archived', archived_at = now() where status = 'active' and id <> $1",
            engagement_id,
        )
        await conn.execute(
            "update engagements set status = 'active', confirmed_at = now(), truthpack_id = $2, name = coalesce("
            "nullif((select name from company_profiles where engagement_id = $1), ''), name) where id = $1",
            engagement_id,
            ctx.truthpack_id,
        )
    _ = eng
    await dashboards.ensure_default(engagement_id, ctx)


# ---------------------------------------------------------------- reads


async def active_id() -> str | None:
    return await db.fetchval("select id::text from engagements where status = 'active' limit 1")


async def resolve(engagement_id: str | None) -> str:
    eid = engagement_id or await active_id()
    if eid is None:
        raise NotFound(
            "No confirmed source of truth yet. Add your files to the knowledge base and fill the dashboard first."
        )
    return eid


async def detail(engagement_id: str, full: bool = True) -> dict:
    e = await _require(engagement_id)
    prof_row = await db.fetchrow("select * from company_profiles where engagement_id = $1", engagement_id)
    prof = _profile_out(prof_row)
    pack = await db.fetchrow(
        "select id, version, confirmed_at, facts from truthpacks where engagement_id = $1 "
        "order by created_at desc limit 1",
        engagement_id,
    )
    out = {
        "id": str(e["id"]),
        "name": e["name"] or (prof or {}).get("name") or "Untitled company",
        "status": e["status"],
        "created_at": e["created_at"],
        "confirmed_at": e["confirmed_at"],
        "profile": prof,
        "profile_sources": (prof_row or {}).get("inferred") or {},
        "truthpack": {"id": str(pack["id"]), "version": pack["version"], "confirmed_at": pack["confirmed_at"]}
        if pack
        else None,
    }
    if not full:
        return out
    uploads = await db.fetch(
        "select id::text, filename, kind::text, status::text, size from uploads "
        "where engagement_id = $1 order by created_at",
        engagement_id,
    )
    ds = await db.fetch(
        """select d.*, m.proposed, m.confirmed from datasets d left join dataset_mappings m on m.dataset_id = d.id
           where d.engagement_id = $1 order by d.created_at""",
        engagement_id,
    )
    extract_jobs = await db.fetch(
        """select id::text, payload->>'upload_id' as upload_id, status::text, error, result from jobs
           where engagement_id = $1 and kind = 'extract' order by enqueued_at desc limit 20""",
        engagement_id,
    )
    ctx = await context(engagement_id)
    out.update(
        uploads=uploads,
        datasets=[_dataset_summary(r) for r in ds],
        extract_jobs=extract_jobs,
        facts=[f for f in (pack["facts"] if pack else []) if f.get("status") != "removed"],
        coverage=coverage(ctx.figures),
        model_notes=model_notes(ctx.model),
    )
    return out


async def list_engagements() -> list[dict]:
    rows = await db.fetch("select id::text from engagements order by created_at desc limit 50")
    return [await detail(r["id"], full=False) for r in rows]


async def truth(engagement_id: str) -> dict:
    ctx = await context(engagement_id)
    pack = await db.fetchrow(
        "select * from truthpacks where engagement_id = $1 order by created_at desc limit 1", engagement_id
    )
    prof = _profile_out(
        await db.fetchrow("select * from company_profiles where engagement_id = $1", engagement_id)
    )
    return {
        "engagement_id": engagement_id,
        "truthpack_id": str(pack["id"]) if pack else None,
        "version": ctx.version,
        "confirmed_at": pack["confirmed_at"] if pack else None,
        "company": ctx.company,
        "profile": prof,
        "figures": [figure_dict(f) for f in ctx.figures.values()],
        "coverage": coverage(ctx.figures),
        "model_notes": model_notes(ctx.model),
        "attack_list": [a.model_dump() for a in ctx.attack],
        "facts": [f.model_dump(mode="json") for f in ctx.facts if f.status != "removed"],
    }


async def require_confirmed(engagement_id: str | None = None) -> str:
    eid = await resolve(engagement_id)
    ok = await db.fetchval(
        "select confirmed_at is not null from truthpacks where engagement_id = $1 "
        "order by created_at desc limit 1",
        eid,
    )
    if not ok:
        raise NotFound("Confirm the source of truth first.")
    return eid
