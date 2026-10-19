"""Regression tests for the leftovers in section 0 of the 2026-10-18 QA report (in git history).

- LLM-6: each live call reserves an estimate of its cost against the day's budget before it is sent and
  settles the difference after, so calls running in parallel can't each overshoot the cap.
- Inline jobs: a semaphore bounds how many run at once (below the DB pool), and a job that waits on other
  jobs gives its slot up while it waits.
- MET-26: the coverage and FX notes from the model reach the engagement detail the UI reads.
"""

import asyncio

import pytest

from tests.llm_fakes import api_error, json_reply, tool_use_reply
from vik import db
from vik.config import get_settings
from vik.llm import minds as agents
from vik.llm.client import BudgetExceeded, LLMUnavailable, get_llm
from vik.llm.schemas import ClaimList, Memo

# ---------------------------------------------------------------- LLM-6: cost reservation

ARGON_CALL_USD = (1000 * 4.0 + 200 * 20.0) / 1e6  # one recorded Gemini 4 Argon call (USAGE in llm_fakes)


def _metric_tool():
    return agents._tool(
        "get_metric",
        "Figure by id.",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        lambda args: {"id": args["id"]},
    )


async def test_llm6_parallel_tool_loops_share_one_overshoot_not_one_each(live_llm, monkeypatch):
    monkeypatch.setenv("DAILY_USD_BUDGET", "0.005")  # less than one Argon call: the first may go, no other
    get_settings.cache_clear()

    async def slow(_call):
        await asyncio.sleep(0.05)  # every loop is in flight before the first answer comes back
        return tool_use_reply("get_metric", {"id": "arr"}, model="gemini-4-argon")

    rec = live_llm.install(slow)
    results = await asyncio.gather(
        *[
            get_llm().run_tools(
                "memo",
                Memo,
                system="memo",
                messages=[{"role": "user", "content": "go"}],
                tools=[_metric_tool()],
            )
            for _ in range(4)
        ],
        return_exceptions=True,
    )
    assert all(isinstance(r, BudgetExceeded) for r in results)
    assert len(rec.calls) == 1, f"{len(rec.calls)} parallel loops each sent a call past the cap"
    # Reservations are settled: the day's spend is exactly what the one call cost.
    assert live_llm.spend == pytest.approx(ARGON_CALL_USD)


async def test_llm6_parallel_parse_calls_reserve_before_sending(live_llm, monkeypatch):
    monkeypatch.setenv("DAILY_USD_BUDGET", "0.0001")
    get_settings.cache_clear()

    async def slow(_call):
        await asyncio.sleep(0.05)
        return json_reply({"claims": []}, model="gemini-3.5-flash-lite")

    rec = live_llm.install(slow)
    results = await asyncio.gather(
        *[
            get_llm().parse("claims", ClaimList, system="claims", messages=[{"role": "user", "content": "x"}])
            for _ in range(3)
        ],
        return_exceptions=True,
    )
    assert len(rec.calls) == 1
    assert sum(isinstance(r, BudgetExceeded) for r in results) == 2
    assert live_llm.spend == pytest.approx((1000 * 0.30 + 200 * 2.50) / 1e6)


async def test_llm6_a_failed_call_gives_its_reservation_back(live_llm):
    live_llm.install(lambda _call: api_error(500, "x"))
    with pytest.raises(LLMUnavailable):
        await get_llm().parse(
            "claims", ClaimList, system="claims", messages=[{"role": "user", "content": "x"}]
        )
    assert live_llm.spend == pytest.approx(0.0)


async def test_llm6_reservations_do_not_count_as_calls(api_client, monkeypatch):
    """The Postgres `spend.calls` counter counts API calls, not reservations or refunds."""
    from datetime import UTC, datetime

    from vik import kv
    from vik.llm.client import LLM

    today = datetime.now(UTC).date()
    saved = await db.fetchrow("select usd, calls from spend where date = $1", today)
    await db.execute("delete from spend where date = $1", today)
    try:
        llm = LLM(client=object())  # no API: only the bookkeeping runs
        held = await llm._reserve(0.5)
        await kv.add_spend(-held, calls=0)
        row = await db.fetchrow("select usd, calls from spend where date = $1", today)
        assert row["usd"] == pytest.approx(0.0) and row["calls"] == 0
    finally:
        await db.execute("delete from spend where date = $1", today)
        if saved:
            await db.execute(
                "insert into spend (date, usd, calls) values ($1, $2, $3)",
                today,
                saved["usd"],
                saved["calls"],
            )


# ---------------------------------------------------------------- inline job concurrency


@pytest.fixture
async def report_jobs(api_client, monkeypatch):
    """Inline `report` jobs run a test handler; the rows are removed afterwards."""
    import vik.services.jobs_handlers  # noqa: F401  (registers the real handlers first)
    from vik import jobs

    ids: list[str] = []

    async def enqueue(payload: dict) -> str:
        jid = await jobs.enqueue("report", payload)
        ids.append(jid)
        return jid

    yield enqueue
    await jobs.wait_for(ids, timeout_s=10)
    await db.execute("delete from jobs where id = any($1::uuid[])", ids)


async def test_inline_jobs_never_hold_more_connections_than_the_limit(report_jobs, monkeypatch):
    from vik import jobs

    assert jobs.INLINE_CONCURRENCY < db.pool().get_max_size(), "jobs must leave connections for requests"
    held = 0
    peak = 0

    async def handler(_payload: dict) -> dict:
        nonlocal held, peak
        async with db.acquire() as conn:
            held += 1
            peak = max(peak, held)
            try:
                await conn.execute("select pg_sleep(0.05)")
            finally:
                held -= 1
        return {}

    monkeypatch.setitem(jobs.HANDLERS, "report", handler)
    ids = [await report_jobs({"n": i}) for i in range(30)]
    await jobs.wait_for(ids, timeout_s=30)
    statuses = await db.fetch("select status::text from jobs where id = any($1::uuid[])", ids)
    assert [r["status"] for r in statuses] == ["done"] * 30
    assert 1 < peak <= jobs.INLINE_CONCURRENCY, f"{peak} inline jobs held connections at once"


async def test_a_job_waiting_on_other_jobs_gives_its_slot_up(report_jobs, monkeypatch):
    """Every slot held by a parent that waits on a child it enqueued must not wedge the queue."""
    from vik import jobs

    async def handler(payload: dict) -> dict:
        if payload.get("child"):
            return {"child": True}
        child = await report_jobs({"child": True})
        await jobs.wait_for([child], timeout_s=5)
        status = await db.fetchval("select status::text from jobs where id = $1", child)
        return {"child_status": status}

    monkeypatch.setitem(jobs.HANDLERS, "report", handler)
    parents = [await report_jobs({"parent": i}) for i in range(jobs.INLINE_CONCURRENCY + 2)]
    await asyncio.wait_for(jobs.wait_for(parents, timeout_s=20), 25)
    rows = await db.fetch("select status::text, result from jobs where id = any($1::uuid[])", parents)
    assert all(r["status"] == "done" for r in rows)
    assert all(r["result"] == {"child_status": "done"} for r in rows), "a parent waited out its child"


# ---------------------------------------------------------------- MET-26: notes reach the UI


def _series(name: str, rows: list[dict], mapping: list[dict], granularity: str = "month"):
    from vik.model.financials import DatasetInput

    return DatasetInput(
        id=name,
        name=name,
        table_kind="series",
        granularity=granularity,
        transposed=False,
        rows=rows,
        mapping=mapping,
    )


def test_met26_model_notes_say_what_was_left_out_in_plain_words():
    from vik.model.context import build_context
    from vik.model.financials import model_notes, model_summary

    pl = _series(
        "pl",
        [{"period": p, "rev": 1000.0} for p in ("2024-07", "2024-08", "2024-09", "2024-10")],
        [{"source_column": "rev", "canonical_field": "revenue.total"}],
    )
    usd = _series(
        "us_sales",
        [{"period": p, "sales": 500.0} for p in ("2025-01", "2025-02", "2025-03")],
        [{"source_column": "sales", "canonical_field": "revenue.total", "unit": "usd"}],
    )
    cash = _series(
        "cash",
        [{"period": "2024-Q3", "cash": 9000.0}, {"period": "2024-Q4", "cash": 8000.0}],
        [{"source_column": "cash", "canonical_field": "cash_balance"}],
        granularity="quarter",
    )
    ctx = build_context([pl, usd, cash], [], {"currency": "cad", "granularity": "quarter"}, fx=None)
    notes = model_notes(ctx.model)
    assert any(n.startswith("Q4 2024 has 1 of 3 months in pl") for n in notes), notes
    fx = [n for n in notes if n.startswith("No USD→CAD rate")]
    assert len(fx) == 1 and "2025-01, 2025-02, 2025-03" in fx[0], notes
    assert model_summary(ctx.model)["messages"] == notes


def test_met26_fx_note_lists_a_few_periods_then_counts_the_rest():
    from vik.model.context import build_context
    from vik.model.financials import model_notes

    periods = [f"2025-{m:02d}" for m in range(1, 13)]
    usd = _series(
        "us",
        [{"period": p, "sales": 1.0} for p in periods],
        [{"source_column": "sales", "canonical_field": "revenue.total", "unit": "usd"}],
    )
    (note,) = model_notes(build_context([usd], [], {"currency": "cad"}, fx=None).model)
    assert "2025-01" in note and "2025-12" not in note and "and 8 more" in note


async def test_met26_engagement_detail_truth_and_dashboard_carry_the_notes(api_client):
    from tests.test_llm_api import _login_and_confirm

    await _login_and_confirm(api_client)
    eng = (await api_client.get("/engagements/active")).json()
    detail = (await api_client.get(f"/engagements/{eng['id']}")).json()
    truth = (await api_client.get("/truth")).json()
    dash = (await api_client.get("/dashboards/active")).json()
    for body in (detail, truth, dash):
        assert isinstance(body.get("model_notes"), list), sorted(body)
