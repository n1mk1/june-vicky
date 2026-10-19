"""The confirmed knowledge base, written back into the vault (docs/08-RAG.md §Indexing).

Confirming the knowledge base (step 04 of the intake) writes one note, `company/Confirmed knowledge base.md`:
the profile with the words each value came from, how every table's columns are read (custom fields included)
and which facts the founder kept. Code writes it from the confirmed TruthPack; figures are not repeated in it
(they come from the metrics engine, never from a note). It is then indexed with the rest of the vault, so retrieval (Ask Vik,
the court, the pitch room's claim checks) can quote what the founder confirmed, not only what they imported.

The note is the vault's own: Fill dashboard never sends it back to the intake, and each confirm rewrites it.
"""

import logging
from datetime import UTC, datetime

from vik import db
from vik.kb.convert import Draft
from vik.kb.store import insert_draft

log = logging.getLogger(__name__)
PATH = "company/Confirmed knowledge base.md"
GENERATED = "confirmed_kb"
PROFILE_LABELS = {
    "name": "Company",
    "one_liner": "What it does",
    "country": "Country",
    "city": "City",
    "currency": "Reporting currency",
    "stage": "Stage",
    "round_type": "Round type",
    "round_size": "Round size",
    "business_model": "Business model",
    "granularity": "Reporting period",
    "fiscal_year_start_month": "Fiscal year starts (month)",
}


def render(
    company: str,
    profile: dict,
    sources: dict,
    datasets: list[dict],
    facts: list[dict],
    targets: dict[str, str],
    confirmed_at: datetime,
) -> str:
    parts = [
        f"# Confirmed knowledge base: {company}",
        f"> Confirmed {confirmed_at:%Y-%m-%d %H:%M} UTC. Written by Vik from the confirmed source of truth: the "
        "profile, how each table's columns are read, and which facts the founder kept. Figures are not repeated "
        "here: they are computed from the confirmed data by the metrics engine.",
    ]
    lines = []
    for k, label in PROFILE_LABELS.items():
        v = profile.get(k)
        if v in (None, ""):
            continue
        if k == "round_size" and isinstance(v, int | float):
            v = f"{v:,.0f} {str(profile.get('currency') or '').upper()}".strip()
        src = sources.get(k) or ""
        lines.append(f"- {label}: {v}." + (f" {src}" if src else ""))
    if lines:
        parts += ["## Company profile", "\n".join(lines)]
    if datasets:
        parts.append("## Tables and how their columns are read")
        for d in datasets:
            src = f" (from [[{d['note']}]])" if d.get("note") else ""
            rows = []
            for m in d["mapping"]:
                col = str(m.get("source_column") or "")
                fid = m.get("canonical_field")
                if fid:
                    name = m.get("label") or targets.get(fid, fid)
                    custom = " (a custom field)" if str(fid).startswith("custom.") else ""
                    rows.append(f"- The column “{col}” is read as {name}{custom}.")
                else:
                    rows.append(f"- The column “{col}” is kept as a raw column.")
            parts += [f"### {d['name']}{src}", "\n".join(rows)]
    kept = [f for f in facts if f.get("status") != "removed"]
    if kept:
        rows = []
        for f in kept:
            when = ", ".join(x for x in (f.get("period"), f.get("kind")) if x)
            ref = (f.get("source") or {}).get("ref") or ""
            rows.append(
                f"- {f.get('label') or f.get('name')}"
                + (f" ({when})" if when else "")
                + (f": from {ref}." if ref else ".")
            )
        parts += ["## Facts the founder kept", "\n".join(rows)]
    return "\n\n".join(parts) + "\n"


async def write(engagement_id: str) -> str:
    """Write (or rewrite) the confirmed-knowledge-base note for an engagement. Returns its note id."""
    from vik.services import engagements

    detail = await engagements.detail(engagement_id, full=False)
    prof = detail.get("profile") or {}
    sources = detail.get("profile_sources") or {}
    rows = await db.fetch(
        """select d.name, coalesce(m.confirmed, m.proposed) as mapping, n.path as note from datasets d
           left join dataset_mappings m on m.dataset_id = d.id
           left join uploads u on u.id = d.upload_id
           left join kb_notes n on n.id = u.kb_note_id
           where d.engagement_id = $1 order by d.created_at""",
        engagement_id,
    )
    pack = await db.fetchrow(
        "select facts from truthpacks where engagement_id = $1 order by created_at desc limit 1",
        engagement_id,
    )
    targets = {t["id"]: t["label"] for t in engagements.mapping_targets()}
    content = render(
        detail.get("name") or "Your company",
        prof,
        sources,
        [{"name": r["name"], "mapping": r["mapping"] or [], "note": r["note"]} for r in rows],
        list(pack["facts"] or []) if pack else [],
        targets,
        datetime.now(UTC),
    )
    meta = {"generated": GENERATED, "engagement_id": engagement_id}
    async with db.acquire() as conn, conn.transaction():
        old = await conn.fetchval(
            "select id::text from kb_notes where meta->>'generated' = $1 order by updated_at desc limit 1",
            GENERATED,
        )
        if old:
            await conn.execute(
                """update kb_notes set content = $2, meta = $3, title = $4, kind = 'document', author = 'ai',
                     summary = $5, organized_at = now(), updated_at = now(), version = version + 1 where id = $1""",
                old,
                content,
                meta,
                "Confirmed knowledge base",
                "What the founder confirmed: profile, column mappings, facts and headline figures.",
            )
            await conn.execute(
                "delete from kb_notes where meta->>'generated' = $1 and id <> $2::uuid", GENERATED, old
            )
            return old
        d = Draft(
            name="Confirmed knowledge base.md",
            title="Confirmed knowledge base",
            kind="document",
            format="md",
            content=content,
            meta=meta,
            tags=["confirmed", "source-of-truth"],
            summary="What the founder confirmed: profile, column mappings, facts and headline figures.",
        )
        nid = await insert_draft(conn, d, path=PATH, file_id=None, author="ai")
        await conn.execute("update kb_notes set organized_at = now() where id = $1", nid)
        return nid
