"""QA probes for retrieval (docs/08-RAG.md), written as the correct behaviour: edge-case queries, caches that
must not leak across currencies or versions, builds that must not hang, offers under concurrency and abuse,
and figure citations that name their knowledge-base note on every path."""

import asyncio
import dataclasses
import json
import pathlib

import pytest

from tests.llm_fakes import json_reply
from tests.test_rag import DECK, QUOTE, _build, vault  # noqa: F401  (fixture)
from vicky import db, jobs
from vicky.audit import audit_text
from vicky.kb import ask, index, rag, store
from vicky.model.context import sample_context

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def ctx():
    return sample_context("tidewell")


# ---------------------------------------------------------------- queries that must not break search


@pytest.mark.parametrize(
    "q",
    [
        "",
        "?",
        "   ",
        "what is the",
        "x" * 10_000,
        "'; drop table kb_notes; --",
        "日本語 😀 Zürich",
        "100% of $250K in Q3",
        "%_\\",
        "[kb:company/Deck.md]",
    ],
)
async def test_odd_queries_never_raise(vault, q):  # noqa: F811
    await _build()
    r = await rag.retrieve(q)
    assert isinstance(r.chunks, list) and 0.0 <= r.confidence <= 1.0
    assert await db.fetchval("select count(*) from kb_notes") >= 2  # still there


async def test_an_empty_vault_text_builds_an_empty_index(api_client):
    await db.execute("delete from kb_index_builds")
    rag.drop_index()
    blank = await store.create_note({"title": "Blank", "path": "misc/Blank", "content": "   \n\n  "})
    try:
        bid = await _build()
        r = await rag.retrieve("anything at all")
        assert r.build_id == bid and r.chunks == []
    finally:
        await store.delete_note(blank["id"])
        await db.execute("delete from kb_index_builds")
        rag.drop_index()


async def test_a_note_deleted_or_renamed_after_the_fill(vault, ctx):  # noqa: F811
    await _build()
    await store.update_note(vault["deck"]["id"], {"path": "company/Pitch deck renamed"})
    r = await rag.retrieve("Zephyrine partnership pilot")
    top = r.chunks[0]
    assert (
        top["path"] == "company/Pitch deck renamed.md" and top["cite"] == "[kb:company/Pitch deck renamed.md]"
    )
    from vicky.kb.tools import Vault

    v = Vault()
    await v.keep_ids([top["note_id"]])
    assert audit_text(
        f"“{QUOTE}” {top['cite']}", ctx.available(), notes=v.notes(), require_citations=True
    ).passed
    await store.delete_note(vault["hiring"]["id"])
    r = await rag.retrieve("hire engineers account executive")
    assert not any(c["note_id"] == vault["hiring"]["id"] for c in r.chunks)


# ---------------------------------------------------------------- caches must not leak


def test_the_answer_cache_keeps_currencies_and_versions_apart(ctx):
    usd = dataclasses.replace(ctx, model=dataclasses.replace(ctx.model, currency="usd"))
    assert ctx.currency != usd.currency
    assert ask._key("b", 1, ctx, "What is ARR?") != ask._key("b", 1, usd, "What is ARR?")
    newer = dataclasses.replace(ctx, version=ctx.version + 1)
    assert ask._key("b", 1, ctx, "What is ARR?") != ask._key("b", 1, newer, "What is ARR?")
    assert ask._guard_key(ctx, "What is ARR?") != ask._guard_key(usd, "What is ARR?")


async def test_an_edit_after_the_fill_invalidates_cached_answers(vault, ctx, live_llm):  # noqa: F811
    await _build()
    reply = f"Your board pack says “{QUOTE}” [kb:{vault['deck']['path']}]"
    rec = live_llm.install(
        lambda call: json_reply({"answerable": True, "reply": reply}, model="claude-haiku-5-5")
    )
    from vicky.qa import answer_any

    q = "What did the board approve for the Zephyrine partnership?"
    await answer_any(q, ctx)
    n = len(rec.calls)
    await store.update_note(vault["hiring"]["id"], {"content": "# Hiring plan\n\nNo hires.\n"})
    again = await answer_any(q, ctx)
    assert len(rec.calls) > n and (again.get("rag") or {}).get("cache") is None


# ---------------------------------------------------------------- builds must not hang


async def test_a_build_does_not_wait_on_an_import_left_running_by_a_dead_process(vault):  # noqa: F811
    await db.execute(
        "insert into jobs (kind, payload, status, enqueued_at, started_at) "
        "values ('kb_ingest', '{}', 'running', now() - interval '2 hours', now() - interval '2 hours')"
    )
    try:
        bid = await asyncio.wait_for(_build(), 20)
        assert bid
    finally:
        await db.execute(
            "delete from jobs where kind = 'kb_ingest' and enqueued_at < now() - interval '1 hour'"
        )


async def test_a_build_whose_job_died_reports_failed_not_building_forever(vault):  # noqa: F811
    first = await _build()
    job = await db.fetchval(
        "insert into jobs (kind, payload, status) values ('kb_index', '{}', 'failed') returning id::text"
    )
    await db.execute(
        "insert into kb_index_builds (status, job_id, started_at) values ('building', $1::uuid, now())", job
    )
    st = await index.status()
    assert st["status"] == "failed" and st["build_id"] == first  # the old index still serves
    b = await index.start_build()  # Retry works
    job2 = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", b["build_id"])
    await jobs.wait_for([job2], 60)
    assert (await index.status())["status"] == "ready"


async def test_every_write_path_bumps_the_vault_version(vault):  # noqa: F811
    v0 = await index.kb_version()
    n = await store.create_note({"title": "Tmp", "path": "misc/Tmp", "content": "x y z"})
    v1 = await index.kb_version()
    await store.update_note(n["id"], {"content": "a b c"})
    v2 = await index.kb_version()
    await db.execute("update kb_notes set summary = 'organizer wrote this' where id = $1::uuid", n["id"])
    v3 = await index.kb_version()
    await store.delete_note(n["id"])
    v4 = await index.kb_version()
    assert v0 < v1 < v2 < v3 < v4


async def test_the_migration_is_idempotent(api_client):
    sql = (pathlib.Path(__file__).resolve().parents[1] / "migrations" / "0006_rag.sql").read_text(
        encoding="utf-8"
    )
    async with db.pool().acquire() as conn:
        for _ in range(2):
            async with conn.transaction():
                await conn.execute(sql)
    assert await db.fetchval("select count(*) from kb_meta") == 1


async def test_concurrent_searches_during_a_rebuild(vault):  # noqa: F811
    await _build()

    async def search(i: int):
        return await rag.retrieve(
            ["Zephyrine partnership", "hire engineers", "pilot customers renewed"][i % 3]
        )

    b = await index.start_build()
    results = await asyncio.gather(*(search(i) for i in range(30)))
    job = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", b["build_id"])
    await jobs.wait_for([job], 60)
    assert all(r.chunks for r in results)
    after = await asyncio.gather(*(search(i) for i in range(30)))
    assert all(r.build_id == b["build_id"] and r.chunks for r in after)


# ---------------------------------------------------------------- offers under abuse and concurrency


async def _dash(api_client) -> str:
    await api_client.post("/auth/access", json={"code": "vicky-demo"})
    d = await api_client.get("/dashboards/active")
    if d.status_code == 404:
        from tests.helpers import load_and_confirm

        await load_and_confirm(api_client, "tidewell")
        d = await api_client.get("/dashboards/active")
    assert d.status_code == 200, (d.status_code, d.text)
    return d.json()["id"]


async def _offer(api_client, did: str) -> dict:
    r = await api_client.post(
        f"/dashboards/{did}/chat", json={"text": "What does the plan say about the purple elephant?"}
    )
    assert r.status_code == 200, r.text
    return r.json()["offer"]


async def test_one_offer_accepted_twice_at_once_runs_one_call(vault, live_llm, api_client):  # noqa: F811
    await _build()
    full = []

    async def respond(call):
        if "holds every note" in json.dumps(call["body"].get("system")):
            full.append(call)
            await asyncio.sleep(0.3)
            return json_reply(
                {"answerable": True, "reply": f"“{QUOTE}” [kb:{vault['deck']['path']}]"},
                model="claude-haiku-5-5",
            )
        return json_reply({"answerable": False, "reply": "no"}, model="claude-haiku-5-5")

    live_llm.install(respond)
    did = await _dash(api_client)
    offer = await _offer(api_client, did)
    body = {"offer_id": offer["id"], "accept": True}
    a, b = await asyncio.gather(
        api_client.post(f"/dashboards/{did}/chat/catch-all", json=body),
        api_client.post(f"/dashboards/{did}/chat/catch-all", json=body),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 410]
    assert len(full) == 1


@pytest.mark.parametrize(
    "body,status",
    [
        ({"offer_id": "not-hex", "accept": True}, 410),
        ({"offer_id": "A" * 32, "accept": True}, 410),
        ({"offer_id": "0" * 32}, 422),
        ({"accept": True}, 422),
        ({"offer_id": "x" * 65, "accept": True}, 422),
    ],
)
async def test_bad_catch_all_requests(vault, api_client, body, status):  # noqa: F811
    did = await _dash(api_client)
    r = await api_client.post(f"/dashboards/{did}/chat/catch-all", json=body)
    assert r.status_code == status, r.text


async def test_the_catch_all_needs_the_access_cookie(vault, api_client):  # noqa: F811
    import httpx

    from vicky.api import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
    ) as anon:
        r = await anon.post("/dashboards/x/chat/catch-all", json={"offer_id": "0" * 32, "accept": True})
    assert r.status_code in (401, 403)


async def test_an_ignored_offer_is_marked_expired(vault, live_llm, api_client):  # noqa: F811
    await _build()
    live_llm.install(lambda call: json_reply({"answerable": False, "reply": "no"}, model="claude-haiku-5-5"))
    did = await _dash(api_client)
    await _offer(api_client, did)
    await db.execute(
        "update rag_misses set created_at = now() - interval '20 minutes' where decision = 'pending'"
    )
    await _offer(api_client, did)
    rows = await db.fetch("select decision from rag_misses order by created_at")
    assert [r["decision"] for r in rows][-2:] == ["expired", "pending"]


# ---------------------------------------------------------------- figures name their knowledge-base note


async def test_figure_footnotes_name_their_note_on_the_offline_path(api_client):
    """Fill dashboard from a CSV note, confirm, then ask a figure question with no API key: the answer comes
    from code, and its footnote still names the note the table came from."""
    from tests.helpers import load_sample_engagement  # noqa: F401
    from vicky.samples import SAMPLES_DIR

    await db.execute("delete from kb_index_builds")
    rag.drop_index()
    await api_client.post("/auth/access", json={"code": "vicky-demo"})
    csv = (SAMPLES_DIR / "tidewell" / "income_statement_monthly.csv").read_text(encoding="utf-8")
    note = await store.create_note(
        {"title": "Income statement", "path": "financials/Income statement", "content": csv, "format": "csv"}
    )
    try:
        r = await api_client.post("/kb/autofill")
        assert r.status_code == 200, r.text
        eid = r.json()["engagement"]["id"]
        c = await api_client.post(f"/engagements/{eid}/confirm")
        assert c.status_code == 200, c.text
        did = (await api_client.get("/dashboards/active")).json()["id"]
        a = await api_client.post(f"/dashboards/{did}/chat", json={"text": "What was revenue in March 2026?"})
        cites = [x for x in a.json()["citations"] if x.get("figure_id")]
        assert cites, a.json()
        assert any((x.get("source") or {}).get("kb_note", {}).get("path") == note["path"] for x in cites), (
            cites
        )
    finally:
        await db.execute("delete from kb_index_builds")
        rag.drop_index()
        await store.delete_note(note["id"])


async def test_an_accepted_offer_says_why_when_nothing_could_be_read(
    vault,  # noqa: F811
    live_llm,
    api_client,
    monkeypatch,
):
    await _build()
    live_llm.install(lambda call: json_reply({"answerable": False, "reply": "no"}, model="claude-haiku-5-5"))
    did = await _dash(api_client)
    offer = await _offer(api_client, did)
    from vicky.llm import client

    async def spent() -> bool:
        return True

    monkeypatch.setattr(client, "over_budget", spent)
    r = await api_client.post(
        f"/dashboards/{did}/chat/catch-all", json={"offer_id": offer["id"], "accept": True}
    )
    assert r.status_code == 200 and "budget is used up" in r.json()["reply"]
    monkeypatch.undo()

    offer = await _offer(api_client, did)  # the model is back for the offer, then down for the accept
    live_llm.install(
        lambda call: (529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    )
    r = await api_client.post(
        f"/dashboards/{did}/chat/catch-all", json={"offer_id": offer["id"], "accept": True}
    )
    assert r.status_code == 200 and "couldn't reach the AI service" in r.json()["reply"]


# ---------------------------------------------------------------- the citation rule under attack (pure)

_NOTE = "The board approved the pilot with 40 stores. Will we raise in Q1? Our U.S. stores grew."
_Q = "“The board approved the pilot with 40 stores.” [kb:a.md]"


@pytest.mark.parametrize(
    "text,ok",
    [
        (_Q, True),
        (_Q + " Churn is falling.", False),
        (_Q[:-1] + "], and churn is falling.", False),  # a comma after the token used to hide a claim
        (_Q + "; churn is falling.", False),
        (_Q + "Churn is falling.", False),  # no space after the token
        (_Q + " (churn is falling)", False),
        ("- " + _Q + "\n- churn is falling", False),
        ("“The board approved the pilot with 40 stores. Will we raise in Q1?” [kb:a.md]", True),
        ("Want me to look at churn?", True),
        (
            "In the U.S. your notes say “Our U.S. stores grew.” [kb:a.md]",
            True,
        ),  # "U.S." is not a sentence end
        ("Your notes say, e.g. “Our U.S. stores grew.” [kb:a.md]", True),
        ("«The board approved the pilot with 40 stores.» [kb:a.md]", True),
        ("Churn is falling [kb:a.md].", False),
    ],
)
def test_every_statement_must_cite_even_under_attack(ctx, text, ok):
    notes = {"a.md": {"id": "1", "path": "a.md", "title": "A", "content": _NOTE}}
    assert audit_text(text, ctx.available(), notes=notes, require_citations=True).passed is ok


def test_an_abbreviation_cannot_hide_the_next_sentence(ctx):
    f = next(f for f in ctx.available() if f.unit in ("cad", "usd", "money"))
    assert not audit_text(
        f"{f.label} is {f.display} in the U.S. It will triple.", ctx.available(), require_citations=True
    ).passed


def test_chunks_are_numbered_without_gaps():
    from vicky.kb.chunk import chunk_note

    content = "## Page 1\n\n## Page 2\n\nText on page two.\n\n## Page 3\n\n## Page 4\n\nMore text."
    assert [c.ord for c in chunk_note(content)] == list(range(len(chunk_note(content))))


async def test_an_oversized_vault_still_gives_the_catch_all_something_to_read(vault, monkeypatch):  # noqa: F811
    from vicky.config import get_settings

    await _build()
    monkeypatch.setattr(get_settings(), "rag_full_max_tokens", 60)  # ~240 characters: less than the two notes
    fits, n = await ask.vault_fits()
    assert not fits and n >= 2
    snap, kept = await ask._snapshot(None)  # recovery found nothing
    total = await db.fetchval("select count(*) from kb_notes")
    assert kept and "<note" in snap and len(kept) < total
    assert sum(len(k["content"]) for k in kept) <= 60 * 4
    r = await rag.retrieve("hire engineers before the next round", mode="recover")
    snap, kept = await ask._snapshot(r)
    assert any(k["path"] == vault["hiring"]["path"] for k in kept)  # the relevant note comes first


async def test_two_fills_at_the_same_instant_leave_exactly_one_active_index(vault):  # noqa: F811
    a, b = await asyncio.gather(index.start_build(), index.start_build())
    ids = [
        await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", x["build_id"])
        for x in (a, b)
    ]
    await jobs.wait_for(ids, 60)
    rows = await db.fetch(
        "select status from kb_index_builds where id = any($1::uuid[])", [a["build_id"], b["build_id"]]
    )
    assert sorted(r["status"] for r in rows) in (["active", "cancelled"], ["active", "superseded"])
    assert await db.fetchval("select count(*) from kb_index_builds where status = 'active'") == 1
    active = await index.active_build_id()
    assert await db.fetchval("select count(distinct build_id) from kb_chunks") == 1
    assert await db.fetchval("select build_id::text from kb_chunks limit 1") == active
