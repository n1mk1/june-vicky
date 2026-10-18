"""Regression tests for the API, security, jobs and infrastructure findings of the 2026-10-18 QA sweep
(docs/qa/QA-REPORT-2026-10-18.md §3.4, §3.7, MET-18 and MET-24). Each test reproduces the report's repro.
"""

import asyncio
import contextlib
import os
import subprocess
import sys
import time
import uuid
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
import yaml

from vicky import BACKEND_DIR
from vicky.config import Settings, get_settings

REPO = BACKEND_DIR.parent


# ---------------------------------------------------------------- helpers


async def _login(api_client) -> None:
    if (await api_client.get("/auth/session")).json().get("ok"):
        return  # the per-IP limit allows five attempts a minute; don't spend them
    r = await api_client.post("/auth/access", json={"code": get_settings().access_code})
    assert r.status_code == 200, r.text


async def _clear_rate_keys() -> None:
    from vicky import kv

    with contextlib.suppress(Exception):
        r = kv.client()
        keys = [k async for k in r.scan_iter("vicky:rl:*")]
        if keys:
            await r.delete(*keys)


@contextlib.contextmanager
def _env(**values: str | None):
    old = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


async def _job(kind: str, status: str, **cols) -> str:
    from vicky import db

    sets = ", ".join(f"{k} = {v}" for k, v in cols.items())
    jid = await db.fetchval(
        "insert into jobs (kind, payload, status) values ($1, '{}'::jsonb, $2::job_status) "
        "returning id::text",
        kind,
        status,
    )
    if sets:
        await db.execute(f"update jobs set {sets} where id::text = $1", jid)
    return jid


async def _status(jid: str) -> tuple[str, str | None]:
    from vicky import db

    row = await db.fetchrow("select status::text, error from jobs where id::text = $1", jid)
    return row["status"], row["error"]


@pytest.fixture
async def handler(api_client, monkeypatch):
    """A controllable handler for the `kb_organize` job kind (no real organizer runs)."""
    import vicky.services.jobs_handlers  # noqa: F401  (registers the real handlers first)
    from vicky import db, jobs

    state = SimpleNamespace(calls=0, started=asyncio.Event(), release=asyncio.Event(), ids=[])

    async def fake(payload: dict) -> dict:
        state.calls += 1
        state.started.set()
        await state.release.wait()
        return {"ok": True}

    monkeypatch.setitem(jobs.HANDLERS, "kb_organize", fake)
    yield state
    state.release.set()
    await asyncio.sleep(0)
    await db.execute("delete from jobs where kind = 'kb_organize' and payload = '{}'::jsonb")


# ---------------------------------------------------------------- API-1: interrupted jobs


@pytest.mark.db
async def test_api1_a_cancelled_job_is_marked_failed_interrupted(handler):
    from vicky import jobs

    jid = await _job("kb_organize", "queued")
    task = asyncio.create_task(jobs.run_job(jid))
    await asyncio.wait_for(handler.started.wait(), 5)
    assert (await _status(jid))[0] == "running"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _status(jid) == ("failed", "interrupted")


@pytest.mark.db
async def test_api1_the_sweeper_marks_long_running_jobs_stale(handler):
    from vicky import jobs

    old = await _job(
        "kb_organize",
        "running",
        started_at="now() - interval '2 hours'",
        enqueued_at="now() - interval '2 hours'",
    )
    fresh = await _job("kb_organize", "running", started_at="now() - interval '1 minute'")
    await jobs.sweep_stale()
    assert (await _status(old))[0] == "stale"
    assert (await _status(fresh))[0] == "running"


@pytest.mark.db
async def test_api1_shutdown_cancels_and_awaits_inline_jobs(handler):
    from vicky import jobs

    before = set(jobs._inline_tasks)
    jid = await jobs.enqueue("kb_organize", {})
    await asyncio.wait_for(handler.started.wait(), 5)
    mine = jobs._inline_tasks - before
    assert len(mine) == 1
    jobs._inline_tasks.difference_update(before)  # leave other tests' jobs alone
    try:
        await jobs.shutdown()
        assert not jobs._inline_tasks and all(t.done() for t in mine)
        assert await _status(jid) == ("failed", "interrupted")
    finally:
        jobs._inline_tasks.update(t for t in before if not t.done())


# ---------------------------------------------------------------- API-2: retry


@pytest.mark.db
async def test_api2_retry_only_requeues_failed_or_stale_jobs(api_client, handler):
    await _login(api_client)
    done = await _job("kb_organize", "done", finished_at="now()")
    r = await api_client.post(f"/jobs/{done}/retry")
    assert r.status_code == 409, r.text
    await asyncio.sleep(0.05)
    assert handler.calls == 0 and (await _status(done))[0] == "done"

    assert (await api_client.post(f"/jobs/{uuid.UUID(int=0)}/retry")).status_code == 404
    assert (await api_client.post("/jobs/not-a-uuid/retry")).status_code == 404
    assert (await api_client.get("/jobs/not-a-uuid")).status_code == 404

    failed = await _job("kb_organize", "failed", error="'boom'")
    r = await api_client.post(f"/jobs/{failed}/retry")
    assert r.status_code == 200, r.text
    await asyncio.wait_for(handler.started.wait(), 5)
    assert (await _status(failed))[0] == "running"
    # Retrying it again while it runs is a conflict, not a second run.
    assert (await api_client.post(f"/jobs/{failed}/retry")).status_code == 409
    handler.release.set()
    for _ in range(100):
        if (await _status(failed))[0] == "done":
            break
        await asyncio.sleep(0.02)
    assert (await _status(failed))[0] == "done" and handler.calls == 1


# ---------------------------------------------------------------- API-3: vectors on every start


@pytest.mark.db
async def test_api3_migrate_ensures_vectors_on_every_start(api_client, monkeypatch):
    from vicky import migrate

    calls = []
    real = migrate.ensure_vectors

    async def spy(conn):
        calls.append(conn)
        return await real(conn)

    monkeypatch.setattr(migrate, "ensure_vectors", spy)
    assert await migrate.migrate(os.environ["DATABASE_URL"]) == []  # nothing new to apply, still checked
    assert len(calls) == 1


@pytest.mark.db
async def test_api3_vector_columns_come_back_once_pgvector_is_available(api_client):
    from vicky import db, migrate

    if not await db.fetchval("select exists (select 1 from pg_available_extensions where name = 'vector')"):
        pytest.skip("pgvector is not installed on this Postgres (use the pgvector/pgvector:pg17 image)")
    await db.execute(
        "drop index if exists kb_chunks_embedding; drop index if exists qa_cache_embedding; "
        "alter table kb_chunks drop column if exists embedding; "
        "alter table qa_cache drop column if exists embedding"
    )
    await migrate.migrate(os.environ["DATABASE_URL"])
    cols = await db.fetch(
        "select table_name, udt_name from information_schema.columns "
        "where column_name = 'embedding' and table_name in ('kb_chunks', 'qa_cache')"
    )
    assert {(c["table_name"], c["udt_name"]) for c in cols} == {
        ("kb_chunks", "halfvec"),
        ("qa_cache", "halfvec"),
    }
    idx = await db.fetch(
        "select indexname from pg_indexes where indexname in ('kb_chunks_embedding', 'qa_cache_embedding')"
    )
    assert len(idx) == 2


# ---------------------------------------------------------------- API-4: render.yaml


def _uncommented_worker(text: str) -> str:
    """render.yaml with the commented-out vicky-worker block switched on (the demo-day step)."""
    out, inside = [], False
    for line in text.splitlines():
        inside = line.startswith("  # - type: worker") or (inside and line.startswith("  # "))
        out.append(line[:2] + line[4:] if inside else line)
    return "\n".join(out)


def test_api4_render_blueprint_parses_and_the_worker_gets_the_voyage_key():
    text = (REPO / "render.yaml").read_text(encoding="utf-8")
    yaml.safe_load(text)
    bp = yaml.safe_load(_uncommented_worker(text))
    services = {s["name"]: s for s in bp["services"]}
    assert "vicky-worker" in services, "the commented worker block should uncomment cleanly"
    groups = {g["name"]: {e["key"] for e in g.get("envVars", [])} for g in bp.get("envVarGroups", [])}

    def keys(svc: dict) -> set[str]:
        out = set()
        for e in svc.get("envVars", []):
            out |= groups.get(e["fromGroup"], set()) if "fromGroup" in e else {e["key"]}
        return out

    api, worker = keys(services["vicky-api"]), keys(services["vicky-worker"])
    assert "VOYAGE_API_KEY" in worker and "VOYAGE_API_KEY" in api
    assert {"DATABASE_URL", "REDIS_URL", "ANTHROPIC_API_KEY", "COOKIE_SECRET"} <= worker
    for g in bp.get("envVarGroups", []):
        for e in g["envVars"]:
            assert "sync" not in e, f"{e['key']}: sync: false is ignored inside an environment group"


# ---------------------------------------------------------------- API-6 / API-7 / MET-18: input validation


@pytest.fixture
async def draft(api_client):
    from vicky import db

    await _login(api_client)
    r = await api_client.post("/engagements", json={"profile": {"name": "Fix API draft", "currency": "cad"}})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    yield eid
    with contextlib.suppress(Exception):
        await db.execute("delete from engagements where id::text = $1 and status = 'draft'", eid)


@pytest.mark.db
@pytest.mark.parametrize(
    "body",
    [
        {"fiscal_year_start_month": "x"},
        {"round_size": "abc"},
        {"profile": [1, 2]},
        {"round_size": 1e20},
        {"round_size": "nan"},
        {"round_size": -5},
    ],
)
async def test_api6_bad_profile_values_are_422(api_client, draft, body):
    r = await api_client.put(f"/engagements/{draft}/profile", json=body)
    assert r.status_code == 422, r.text


@pytest.mark.db
async def test_api6_good_profile_values_still_save(api_client, draft):
    r = await api_client.put(
        f"/engagements/{draft}/profile", json={"round_size": "2500000", "fiscal_year_start_month": "4"}
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["profile"]["round_size"] == 2_500_000 and r.json()["profile"]["fiscal_year_start_month"] == 4
    )


@pytest.mark.db
@pytest.mark.parametrize("raw", ["Infinity", "-Infinity", "NaN"])
async def test_api7_nan_or_infinity_in_a_value_is_422(api_client, draft, raw):
    headers = {"content-type": "application/json"}
    r = await api_client.post(
        f"/engagements/{draft}/facts", content=f'{{"name":"x","value":{raw}}}', headers=headers
    )
    assert r.status_code == 422, r.text
    r = await api_client.post(
        f"/claims/check?engagement_id={draft}", headers=headers, content=f'{{"metric":"arr","value":{raw}}}'
    )
    assert r.status_code == 422, r.text


@pytest.mark.db
async def test_met18_fact_units_are_checked_and_money_takes_the_reporting_currency(api_client, draft):
    r = await api_client.post(
        f"/engagements/{draft}/facts", json={"name": "x", "value": 1, "unit": "furlongs"}
    )
    assert r.status_code == 422, r.text
    for unit in ("$", "money", "USD"):
        r = await api_client.post(
            f"/engagements/{draft}/facts", json={"name": f"round_{unit}", "value": 4e6, "unit": unit}
        )
        assert r.status_code == 200, r.text
    units = {f["name"]: f["unit"] for f in r.json()["facts"]}
    assert units["round_$"] == "cad" and units["round_money"] == "cad" and units["round_usd"] == "usd"


# ---------------------------------------------------------------- API-8: rotating the access code


def test_api8_changing_access_code_revokes_issued_cookies():
    from itsdangerous import BadSignature

    from vicky import auth, realtime

    with _env(ACCESS_CODE="first-code", COOKIE_SECRET="s3cret"):
        token = auth.make_token()
        ws_token = realtime._ws_signer().sign(b"ws").decode()
        assert auth.token_ok(token)
    with _env(ACCESS_CODE="second-code", COOKIE_SECRET="s3cret"):
        assert not auth.token_ok(token)
        assert auth.token_ok(auth.make_token())
        with pytest.raises(BadSignature):  # the socket token goes with the cookie
            realtime._ws_signer().unsign(ws_token, max_age=60)
    with _env(ACCESS_CODE="first-code", COOKIE_SECRET="s3cret"):
        assert auth.token_ok(token)


# ---------------------------------------------------------------- API-9: X-Forwarded-For


def _req(peer: str, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_api9_forwarded_for_is_only_honoured_from_trusted_proxies():
    from vicky.auth import client_ip

    assert client_ip(_req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"  # a direct client can't pick its IP
    assert (
        client_ip(_req("10.1.2.3", "1.2.3.4, 198.51.100.7")) == "198.51.100.7"
    )  # rightmost hop our proxy added
    assert (
        client_ip(_req("10.1.2.3", "198.51.100.7, 10.9.9.9")) == "198.51.100.7"
    )  # internal hops are skipped
    assert client_ip(_req("127.0.0.1", "10.0.0.1, 10.0.0.2")) == "10.0.0.1"  # all internal: the first one
    assert client_ip(_req("10.1.2.3")) == "10.1.2.3"
    assert client_ip(_req("10.1.2.3", "garbage, 198.51.100.7")) == "198.51.100.7"
    with _env(TRUSTED_PROXY_CIDRS=""):
        assert client_ip(_req("10.1.2.3", "1.2.3.4")) == "10.1.2.3"
    # uvicorn must not rewrite the peer from the header first (with '*' it took the leftmost, spoofable entry).
    script = [
        ln
        for ln in (BACKEND_DIR / "entrypoint.sh").read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    ]
    assert not any("forwarded-allow-ips" in ln for ln in script) and any(
        "--no-proxy-headers" in ln for ln in script
    )


@pytest.mark.db
async def test_api9_rotating_forwarded_for_from_the_internet_still_hits_the_limit(api_client):
    from vicky.api import app

    await _clear_rate_keys()
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 40000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
            codes = [
                (
                    await c.post(
                        "/auth/access", json={"code": "wrong"}, headers={"x-forwarded-for": f"198.51.100.{i}"}
                    )
                ).status_code
                for i in range(8)
            ]
        assert codes[0] == 401 and 429 in codes, codes
    finally:
        await _clear_rate_keys()


@pytest.mark.db
async def test_api9_failed_codes_are_capped_across_all_addresses(api_client):
    await _clear_rate_keys()
    try:
        with _env(ACCESS_FAILURES_PER_MIN="3"):
            codes = [
                (
                    await api_client.post(
                        "/auth/access", json={"code": "wrong"}, headers={"x-forwarded-for": f"198.51.100.{i}"}
                    )
                ).status_code
                for i in range(5)
            ]
        assert codes[:3] == [401, 401, 401] and codes[-1] == 429, codes
    finally:
        await _clear_rate_keys()
        await _login(api_client)


# ---------------------------------------------------------------- API-10: interactive docs


@pytest.mark.parametrize(
    "secure,expect", [("true", "None None None"), ("false", "/docs /redoc /openapi.json")]
)
def test_api10_interactive_docs_are_off_in_production(secure, expect):
    env = {
        **os.environ,
        "COOKIE_SECURE": secure,
        "ACCESS_CODE": "a-real-code",
        "COOKIE_SECRET": "a-real-secret",
    }
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from vicky.api import app; print(app.docs_url, app.redoc_url, app.openapi_url)",
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == expect


# ---------------------------------------------------------------- API-11: health


@pytest.mark.db
async def test_api11_healthz_is_503_when_the_database_is_down(api_client, monkeypatch):
    from vicky import db, kv

    async def down(*_a, **_k):
        raise ConnectionError("db down")

    monkeypatch.setattr(db, "fetchval", down)
    r = await api_client.get("/healthz")
    assert r.status_code == 503 and r.json()["db"] == "error"
    monkeypatch.undo()

    def no_kv():
        raise RuntimeError("redis is not initialised")

    monkeypatch.setattr(kv, "client", no_kv)
    r = await api_client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"db": "ok", "kv": "error"}


# ---------------------------------------------------------------- API-14 / KB-21: request size cap


@pytest.mark.db
async def test_api14_oversized_bodies_are_413_before_they_are_read(api_client):
    await _login(api_client)
    big = {"profile": {"name": "x" * 5000}}
    with _env(REQUEST_MAX_BYTES="2000"):
        r = await api_client.post("/engagements", json=big)
        assert r.status_code == 413, r.text

        async def chunks():  # no content-length: counted as it streams
            for _ in range(10):
                yield b" " * 500

        r = await api_client.post(
            "/engagements", content=chunks(), headers={"content-type": "application/json"}
        )
        assert r.status_code == 413, r.text
        assert (await api_client.get("/healthz")).status_code == 200


def test_api14_the_default_cap_leaves_room_for_a_full_size_kb_file():
    s = Settings()
    assert s.max_request_bytes() > s.kb_upload_max_bytes and s.max_request_bytes() > s.upload_max_bytes
    assert Settings(request_max_bytes=1234).max_request_bytes() == 1234


# ---------------------------------------------------------------- API-15: rate key TTL


@pytest.mark.db
async def test_api15_a_rate_key_without_ttl_gets_one_back(api_client):
    from vicky import auth, kv

    key = "vicky:rl:access:fix-api-test"
    r = kv.client()
    await r.delete(key)
    await r.set(key, 2)  # INCR landed, EXPIRE never did (crash, timeout)
    assert await r.ttl(key) == -1
    assert await auth._rate(key, 5, 60)
    assert 0 < await r.ttl(key) <= 60
    await r.delete(key)


# ---------------------------------------------------------------- API-16: Bank of Canada fetches


@pytest.fixture
def fx_cache(monkeypatch):
    from vicky.services import fx

    store: dict = {}

    async def cached(code, year):
        return store.get((code, year))

    async def put(code, year, obs, now):
        store[(code, year)] = {"fetched": now.isoformat(), "obs": obs}

    monkeypatch.setattr(fx, "_cached", cached)
    monkeypatch.setattr(fx, "_store", put)
    fx._down.clear()
    yield store
    fx._down.clear()


def _valet(request: httpx.Request) -> httpx.Response:
    sid = request.url.path.split("/")[-2].split(",")
    year = request.url.params["start_date"][:4]
    return httpx.Response(
        200, json={"observations": [{"d": f"{year}-01-02", **{s: {"v": "1.5"} for s in sid}}]}
    )


async def test_api16_years_are_fetched_together(fx_cache):
    from vicky.services import fx

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return _valet(request)

    since = date(date.today().year - 4, 1, 1)
    t0 = time.monotonic()
    r = await fx.load({"usd"}, since, transport=httpx.MockTransport(slow))
    assert time.monotonic() - t0 < 1.0  # five years one at a time would take 1.5 s
    assert len(r.daily["usd"]) == 5


async def test_api16_an_overall_deadline_bounds_a_hanging_api_and_failures_are_remembered(
    fx_cache, monkeypatch
):
    from vicky.services import fx

    calls = []

    async def hang(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await asyncio.sleep(30)
        return _valet(request)

    monkeypatch.setattr(fx, "DEADLINE_S", 0.3)
    t0 = time.monotonic()
    r = await fx.load({"usd"}, date(date.today().year - 2, 1, 1), transport=httpx.MockTransport(hang))
    assert time.monotonic() - t0 < 1.5 and r.daily == {}
    n = len(calls)
    assert n == 3
    t0 = time.monotonic()
    await fx.load({"usd"}, date(date.today().year - 2, 1, 1), transport=httpx.MockTransport(hang))
    assert len(calls) == n and time.monotonic() - t0 < 0.2  # the failure is cached: no new calls

    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    fx._down.clear()
    seen = []

    def counted(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return down(request)

    await fx.load({"eur"}, transport=httpx.MockTransport(counted))
    await fx.load({"eur"}, transport=httpx.MockTransport(counted))
    assert len(seen) == 1


# ---------------------------------------------------------------- MET-24: confirm and low-confidence proposals


@pytest.mark.db
async def test_met24_confirm_keeps_low_confidence_proposals_raw(api_client):
    from vicky import db

    await _login(api_client)
    csv = b"Month,Revenue,Total costs\n2025-01,100,50\n2025-02,120,55\n2025-03,130,60\n"
    r = await api_client.post("/uploads", files={"file": ("fix_api_low_conf.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    eng = r.json()
    try:
        ds = eng["datasets"][0]
        # As proposed (whatever the heuristic rules say today): one column below the review threshold.
        await db.execute(
            "update dataset_mappings set proposed = $2, proposer = 'heuristic' where dataset_id::text = $1",
            ds["id"],
            [
                {"source_column": "Month", "canonical_field": "period", "unit": "date", "confidence": 0.95},
                {
                    "source_column": "Revenue",
                    "canonical_field": "revenue.total",
                    "unit": "cad",
                    "confidence": 0.9,
                },
                {
                    "source_column": "Total costs",
                    "canonical_field": "opex.total",
                    "unit": "cad",
                    "confidence": 0.55,
                },
            ],
        )
        active = await db.fetchval("select id::text from engagements where status = 'active'")
        r = await api_client.post(f"/engagements/{eng['id']}/confirm")
        # The confirm goes through without a manual step, but the low-confidence guess never reaches the
        # metrics: it is kept as a raw column, and the table says so.
        assert r.status_code == 200, r.text
        m = (await api_client.get(f"/datasets/{ds['id']}/mapping")).json()
        cost = next(c for c in m["confirmed"] if c["source_column"] == "Total costs")
        assert cost["canonical_field"] is None and "low confidence" in cost["note"]
        assert (
            next(c for c in m["confirmed"] if c["source_column"] == "Revenue")["canonical_field"]
            == "revenue.total"
        )
        assert any("Total costs" in n for n in m["dataset"]["notes"])
    finally:
        await db.execute("delete from engagements where id::text = $1", eng["id"])
        if active:  # the sample stays the source of truth for the tests after this one
            await db.execute("update engagements set status = 'active' where id::text = $1", active)


def test_met24_a_reviewed_or_confident_mapping_needs_no_review():
    from vicky.services.engagements import needs_review

    low = {"source_column": "Total costs", "canonical_field": "opex.total", "confidence": 0.55}
    ok = {"source_column": "Revenue", "canonical_field": "revenue.total", "confidence": 0.9}
    raw = {"source_column": "Notes", "canonical_field": None, "confidence": 0.3}
    assert needs_review([low, ok, raw], "heuristic") == ["Total costs"]
    assert needs_review([ok, raw], "heuristic") == []
    assert needs_review([low], "reused") == []  # a mapping the founder confirmed before
