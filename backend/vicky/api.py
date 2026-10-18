"""FastAPI app: lifespan (DB pool, migrations under an advisory lock, Redis, realtime hub) and the
REST surface in docs/API.md. Every route under /api/v1 needs the access cookie except
/healthz and /auth/*.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from vicky import auth, db, jobs, kv, memory, migrate, realtime, report
from vicky.areopagus import builder, registry
from vicky.areopagus.registry import PersonaError
from vicky.config import get_settings
from vicky.court import session as court
from vicky.court.session import CourtError
from vicky.kb import routes as kb_routes
from vicky.model import sources as src
from vicky.model.figures import figure_dict
from vicky.model.truth import check_claim
from vicky.services import dashboards, engagements
from vicky.services.dashboards import Conflict
from vicky.services.engagements import FACT_UNITS, Invalid, NotFound
from vicky.viz.dsl import DSLError

log = logging.getLogger("vicky")


async def _sweeper() -> None:
    while True:  # first pass at startup: rows a previous process left `running` become retryable
        with contextlib.suppress(Exception):
            await jobs.sweep_stale()
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    s = get_settings()
    if s.cookie_secure and (s.access_code == "vicky-demo" or s.cookie_secret == "dev-only-change-me"):
        raise RuntimeError("Set ACCESS_CODE and COOKIE_SECRET: the development defaults must not guard a public deploy")
    await migrate.migrate(s.database_url)
    await db.connect(s.database_url)
    await kv.connect(s.redis_url)
    await realtime.hub.start()
    sweeper = asyncio.create_task(_sweeper())
    log.info("vicky api ready (jobs=%s, llm=%s)", s.jobs_mode, s.llm_mode)
    try:
        yield
    finally:
        sweeper.cancel()
        await jobs.shutdown()  # inline jobs still running are cancelled and marked interrupted
        await realtime.hub.stop()
        await kv.close()
        await db.close()


class BodyLimit:
    """413 for a request body over REQUEST_MAX_BYTES: refused up front by its content-length, or as
    soon as a streamed (chunked) body passes the cap, so nothing big is ever buffered."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = get_settings().max_request_bytes()
        length = dict(scope.get("headers") or ()).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            return await self._too_large(scope, receive, send, limit)
        seen, started, rejected = 0, False, False

        async def limited_receive():
            nonlocal seen, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    # Answer 413 now; the app sees the client go away and whatever it sends is dropped.
                    rejected = True
                    if not started:
                        await self._too_large(scope, receive, send, limit)
                    return {"type": "http.disconnect"}
            return message

        async def tracked_send(message) -> None:
            nonlocal started
            if rejected:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except Exception:
            if not rejected:
                raise

    @staticmethod
    async def _too_large(scope, receive, send, limit: int) -> None:
        size = f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit} bytes"
        await JSONResponse({"detail": f"Requests are limited to {size}."}, status_code=413)(scope, receive, send)


def docs_urls(cookie_secure: bool) -> dict:
    """The interactive docs and schema are for local development; a public deploy (COOKIE_SECURE) serves none."""
    if cookie_secure:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


app = FastAPI(title="Vicky API", version="0.1.0", lifespan=lifespan, **docs_urls(get_settings().cookie_secure))
app.add_middleware(BodyLimit)  # inside CORS, so a 413 still carries the CORS headers
app.add_middleware(CORSMiddleware, allow_origins=[get_settings().web_origin], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(NotFound)
async def _nf(_: Request, e: NotFound):
    return JSONResponse({"detail": str(e) if " " in str(e) else f"{str(e).capitalize()} not found"}, status_code=404)


@app.exception_handler(Invalid)
async def _inv(_: Request, e: Invalid):
    return JSONResponse({"detail": str(e)}, status_code=422)


@app.exception_handler(Conflict)
async def _conf(_: Request, e: Conflict):
    return JSONResponse({"detail": str(e)}, status_code=409)


@app.exception_handler(RequestValidationError)
async def _req_val(_: Request, e: RequestValidationError):
    # FastAPI's default 422, without echoing the input: a NaN or Infinity there isn't valid JSON (500).
    return JSONResponse({"detail": jsonable_encoder([{k: v for k, v in err.items() if k != "input"}
                                                     for err in e.errors()])}, status_code=422)


@app.exception_handler(ValidationError)
async def _val(_: Request, e: ValidationError):
    first = e.errors()[0]
    where = ".".join(str(x) for x in first.get("loc", ()))
    return JSONResponse({"detail": f"{where}: {first.get('msg')}" if where else first.get("msg")}, status_code=422)


@app.exception_handler(DSLError)
async def _dsl(_: Request, e: DSLError):
    return JSONResponse({"detail": e.message}, status_code=422)


# ---------------------------------------------------------------- health (open)

async def health() -> JSONResponse:
    """503 when Postgres is unreachable, so Render's health check restarts a broken instance. Redis is
    reported but doesn't fail the check: every Redis use degrades gracefully."""
    out = {"db": "error", "kv": "error"}
    with contextlib.suppress(Exception):
        await db.fetchval("select 1")
        out["db"] = "ok"
    with contextlib.suppress(Exception):
        await kv.client().ping()
        out["kv"] = "ok"
    return JSONResponse(out, status_code=200 if out["db"] == "ok" else 503)


app.add_api_route("/healthz", health, methods=["GET"])

open_api = APIRouter(prefix="/api/v1")
open_api.add_api_route("/healthz", health, methods=["GET"])
open_api.include_router(auth.router)
open_api.include_router(realtime.router)  # /ws checks the cookie itself; /realtime/token is gated per route

api = APIRouter(prefix="/api/v1", dependencies=[auth.Gate])


# ---------------------------------------------------------------- engagements and truth

class ProfileIn(BaseModel):
    profile: dict = Field(default_factory=dict)


class FactIn(BaseModel):
    name: str
    label: str | None = None
    value: float = Field(allow_inf_nan=False)
    unit: str = "count"  # a unit in model.figures.UNITS, or "money" / "$" for the reporting currency
    period: str | None = None
    kind: str | None = None
    note: str | None = None

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        unit = (v or "count").strip().lower()
        if unit not in FACT_UNITS:
            raise ValueError(f"unknown unit {v!r}; use a currency code, money, pct, months, count, ratio or x")
        return unit


class MappingIn(BaseModel):
    mapping: list[dict]


class ClaimIn(BaseModel):
    metric: str
    value: float = Field(allow_inf_nan=False)
    unit: str = ""
    period: str | None = None
    is_forecast: bool = False


@api.get("/engagements")
async def list_engagements() -> list[dict]:
    return await engagements.list_engagements()


@api.get("/engagements/active")
async def active_engagement() -> dict:
    eid = await engagements.active_id()
    if eid is None:
        raise NotFound("No confirmed source of truth yet. Add your files to the knowledge base and fill the dashboard first.")
    return await engagements.detail(eid)


@api.post("/engagements")
async def create_engagement(body: ProfileIn) -> dict:
    return await engagements.detail(await engagements.create_engagement(body.profile))


@api.get("/engagements/{eid}")
async def get_engagement(eid: str) -> dict:
    return await engagements.detail(eid)


@api.put("/engagements/{eid}/profile")
async def put_profile(eid: str, body: dict) -> dict:
    await engagements.update_profile(eid, body.get("profile", body))
    return await engagements.detail(eid)


@api.post("/uploads")
async def upload(file: UploadFile = File(...), engagement_id: str | None = Form(None)) -> dict:
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Files are limited to {limit // (1024 * 1024)} MB")
    try:
        eid = await engagements.add_upload(engagement_id or None, file.filename or "upload", data, file.content_type or "")
    except Invalid as e:
        raise HTTPException(415 if "Unsupported" in str(e) else 422, str(e)) from e
    return await engagements.detail(eid)


@api.get("/datasets/{dsid}/mapping")
async def get_mapping(dsid: str) -> dict:
    return await engagements.get_mapping(dsid)


@api.put("/datasets/{dsid}/mapping")
async def put_mapping(dsid: str, body: MappingIn) -> dict:
    return await engagements.put_mapping(dsid, body.mapping)


@api.post("/engagements/{eid}/facts")
async def add_fact(eid: str, body: FactIn) -> dict:
    await engagements.add_fact(eid, body.model_dump())
    return await engagements.detail(eid)


@api.delete("/engagements/{eid}/facts/{fact_id}")
async def remove_fact(eid: str, fact_id: str) -> dict:
    await engagements.remove_fact(eid, fact_id)
    return await engagements.detail(eid)


@api.post("/engagements/{eid}/confirm")
async def confirm(eid: str) -> dict:
    await engagements.confirm(eid)
    return await engagements.detail(eid)


@api.get("/truth")
async def truth(engagement_id: str | None = None) -> dict:
    return await engagements.truth(await engagements.resolve(engagement_id))


@api.get("/metrics")
async def metrics(engagement_id: str | None = None) -> list[dict]:
    ctx = await engagements.context(await engagements.resolve(engagement_id))
    return [figure_dict(f) for f in ctx.figures.values()]


@api.get("/metrics/{mid}")
async def metric(mid: str, engagement_id: str | None = None) -> dict:
    ctx = await engagements.context(await engagements.resolve(engagement_id))
    f = ctx.figures.get(mid)
    if f is None:
        raise NotFound(f"No metric called {mid}")
    return figure_dict(f)


@api.get("/attack-list")
async def attack_list(lens: str | None = None, engagement_id: str | None = None) -> list[dict]:
    ctx = await engagements.context(await engagements.resolve(engagement_id))
    return [a.model_dump() for a in ctx.attack if lens is None or a.lens == lens]


@api.get("/coverage")
async def coverage(engagement_id: str | None = None) -> list[dict]:
    from vicky.model.coverage import coverage as cov

    ctx = await engagements.context(await engagements.resolve(engagement_id))
    return cov(ctx.figures)


@api.post("/claims/check")
async def claims_check(body: ClaimIn, engagement_id: str | None = None) -> dict:
    ctx = await engagements.context(await engagements.resolve(engagement_id))
    return check_claim(body.metric, body.value, body.unit, ctx.figures, period=body.period, is_forecast=body.is_forecast,
                       facts=ctx.facts).model_dump(mode="json")


@api.get("/glossary")
async def glossary(term: str | None = None) -> list[dict]:
    if term:
        g = src.define_term(term)
        return [g] if g else []
    return src.glossary()


@api.get("/sources")
async def sources(topic: str | None = None) -> list[dict]:
    return src.cite_source(topic) if topic else src.sources()


# ---------------------------------------------------------------- dashboards

class SpecIn(BaseModel):
    spec: dict
    version: int | None = None


class LayoutIn(BaseModel):
    layout: list[dict]
    version: int | None = None


@api.get("/dashboards/active")
async def dashboard_active(theme: str = "vicky-dark", currency: str | None = None) -> dict:
    return await dashboards.active(theme, currency)


@api.get("/dashboards/{did}")
async def dashboard(did: str, theme: str = "vicky-dark", currency: str | None = None) -> dict:
    return await dashboards.get(did, theme, currency)


@api.post("/dashboards/{did}/widgets/preview")
async def widget_preview(did: str, body: SpecIn, theme: str = "vicky-dark", currency: str | None = None) -> dict:
    return await dashboards.preview(did, body.spec, theme, currency)


@api.post("/dashboards/{did}/widgets")
async def widget_add(did: str, body: SpecIn, currency: str | None = None) -> dict:
    return await dashboards.add_widget(did, body.spec, body.version, currency=currency)


@api.delete("/dashboards/{did}/widgets/{wid}")
async def widget_remove(did: str, wid: str, currency: str | None = None) -> dict:
    return await dashboards.remove_widget(did, wid, currency)


@api.patch("/dashboards/{did}/layout")
async def layout(did: str, body: LayoutIn, currency: str | None = None) -> dict:
    return await dashboards.set_layout(did, body.layout, body.version, currency)


class TimeRangeIn(BaseModel):
    time_range: dict | None = None
    version: int | None = None


@api.patch("/dashboards/{did}/time-range")
async def time_range(did: str, body: TimeRangeIn, currency: str | None = None) -> dict:
    return await dashboards.set_time_range(did, body.time_range, body.version, currency)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@api.post("/dashboards/{did}/chat")
async def dashboard_chat(did: str, body: ChatIn, currency: str | None = None) -> dict:
    return await dashboards.chat(did, body.text, currency)


class CatchAllIn(BaseModel):
    offer_id: str = Field(min_length=1, max_length=64)
    accept: bool


@api.post("/dashboards/{did}/chat/catch-all", response_model=None)
async def dashboard_catch_all(did: str, body: CatchAllIn, currency: str | None = None) -> dict | PlainTextResponse:
    """The user's answer to a catch-all offer (docs/08-RAG.md §Asking permission): accept runs the
    whole-vault call once; decline runs nothing (204); an expired, used or foreign offer is 410."""
    from vicky.kb.ask import OfferGone

    try:
        out = await dashboards.catch_all(did, body.offer_id, body.accept, currency)
    except OfferGone as e:
        raise HTTPException(410, str(e)) from e
    if out is None:
        return PlainTextResponse("", status_code=204)
    return out


# ---------------------------------------------------------------- areopagus

@api.get("/areopagus")
async def personas() -> list[dict]:
    return [p.summary() for p in await registry.all_personas()]


@api.get("/areopagus/templates")
async def persona_templates() -> list[dict]:
    return [t.model_dump(mode="json") for t in registry.templates()]


@api.get("/areopagus/options")
async def persona_options() -> dict:
    return builder.options()


class PersonaDescribe(BaseModel):
    description: str = Field(min_length=10, max_length=2000)


@api.post("/areopagus/generate")
async def persona_generate(body: PersonaDescribe) -> dict:
    """A draft persona from a description (Claude, or the keyword heuristic offline). Not saved."""
    p, source = await builder.generate(body.description)
    return {"persona": p.model_dump(mode="json"), "source": source}


@api.get("/areopagus/{pid}")
async def persona(pid: str) -> dict:
    p = await registry.get(pid)
    if p is None:
        raise NotFound(f"No investor called {pid}")
    return p.model_dump(mode="json")


@api.post("/areopagus")
async def persona_create(body: dict) -> dict:
    return (await registry.create(body)).model_dump(mode="json")


@api.put("/areopagus/{pid}")
async def persona_update(pid: str, body: dict) -> dict:
    try:
        return (await registry.update(pid, body)).model_dump(mode="json")
    except PersonaError as e:
        raise HTTPException(403, str(e)) from e
    except KeyError as e:
        raise NotFound(f"No investor called {pid}") from e


@api.delete("/areopagus/{pid}")
async def persona_delete(pid: str) -> dict:
    try:
        await registry.delete(pid)
    except PersonaError as e:
        raise HTTPException(403, str(e)) from e
    except KeyError as e:
        raise NotFound(f"No investor called {pid}") from e
    return {"ok": True}


@api.post("/areopagus/{pid}/fork")
async def persona_fork(pid: str) -> dict:
    try:
        return (await registry.fork(pid)).model_dump(mode="json")
    except KeyError as e:
        raise NotFound(f"No investor called {pid}") from e


# ---------------------------------------------------------------- court

class CourtStart(BaseModel):
    panel: list[str] | None = None
    question_cap: int | None = Field(default=None, ge=4, le=20)
    coaching: str | None = None
    focus: str | None = Field(default=None, max_length=500)
    knowledge: bool = True  # knowledge checks from the founder's notes (needs the search index)
    drills: list[str] | None = Field(default=None, max_length=20)  # founder_memory drill ids; default: every pending one


class DrillItem(BaseModel):
    seq: int = Field(ge=1)
    mark: Literal["repeat", "study"]


class DrillsIn(BaseModel):
    items: list[DrillItem] = Field(min_length=1, max_length=20)


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@api.post("/court/start", dependencies=[auth.Budget])
async def court_start(body: CourtStart) -> dict:
    try:
        await engagements.require_confirmed()
    except NotFound as e:
        raise HTTPException(409, str(e)) from e
    try:
        sid = await court.start(body.panel, body.question_cap, body.coaching, body.focus, body.knowledge, body.drills)
    except (PersonaError, CourtError) as e:
        raise HTTPException(422, str(e)) from e
    return await court.view(sid)


@api.get("/court/{sid}")
async def court_view(sid: str) -> dict:
    return await court.view(sid)


@api.post("/court/{sid}/answer", dependencies=[auth.Budget])
async def court_answer(sid: str, body: AnswerIn) -> dict:
    try:
        await court.answer(sid, body.text)
    except CourtError as e:
        raise HTTPException(409, str(e)) from e
    return await court.view(sid)


@api.post("/court/{sid}/drills")
async def court_drills(sid: str, body: DrillsIn) -> dict:
    """Save the questions marked Repeat / Study as drills (`founder_memory`); the next session starts with them."""
    try:
        saved = await memory.save_drills(sid, [i.model_dump() for i in body.items])
    except KeyError as e:
        raise NotFound("No such session") from e
    if not saved:
        raise HTTPException(422, "None of those questions are in this session")
    return {"drills": saved}


@api.post("/court/{sid}/end")
async def court_end(sid: str) -> dict:
    await court.end(sid)
    return await court.view(sid)


@api.get("/sessions")
async def sessions_list() -> list[dict]:
    return await court.list_sessions()


@api.get("/sessions/{sid}/report")
async def session_report(sid: str) -> dict:
    rid = await db.fetchval("select id::text from reports where session_id::text = $1", sid)
    if rid is None:
        raise NotFound("No report for this session yet")
    return await report_get(rid)


# ---------------------------------------------------------------- reports

@api.get("/reports")
async def reports() -> list[dict]:
    rows = await db.fetch(
        """select r.id::text, r.session_id::text, r.created_at, r.overall::float, r.readiness, e.name as company,
                  r.dims, r.delta_vs_previous::float as delta, s.settings->>'focus' as focus,
                  coalesce((select jsonb_agg(jsonb_build_object('id', v->>'vc_id', 'name', v->>'name'))
                            from jsonb_array_elements(coalesce(r.report->'per_vc', '[]'::jsonb)) v), '[]'::jsonb) as vcs,
                  (select array_agg(q->>'lens')
                     from jsonb_array_elements(coalesce(r.report->'questions', '[]'::jsonb)) q) as lenses
           from reports r join engagements e on e.id = r.engagement_id
           left join sessions s on s.id = r.session_id
           order by r.created_at desc limit 50""")
    for r in rows:
        r["summary"] = report.describe(r.pop("lenses"), r.pop("focus"))
    return rows


@api.get("/reports/{rid}.md", response_class=PlainTextResponse)
async def report_md(rid: str) -> PlainTextResponse:
    md = await db.fetchval("select markdown from reports where id::text = $1", rid)
    if md is None:
        raise NotFound("report")
    return PlainTextResponse(md, media_type="text/markdown",
                             headers={"content-disposition": f'attachment; filename="vicky-report-{rid[:8]}.md"'})


@api.get("/reports/{rid}")
async def report_get(rid: str) -> dict:
    row = await db.fetchrow("select * from reports where id::text = $1", rid)
    if row is None:
        raise NotFound("report")
    return {"id": str(row["id"]), "session_id": str(row["session_id"]), "created_at": row["created_at"],
            "markdown": row["markdown"], **row["report"]}


# ---------------------------------------------------------------- jobs

@api.get("/jobs/{jid}")
async def job_status(jid: str) -> dict:
    row = await db.fetchrow("select id::text, kind::text, status::text, error, result, enqueued_at, finished_at "
                            "from jobs where id::text = $1", jid)
    if row is None:
        raise NotFound("job")
    return row


@api.post("/jobs/{jid}/retry")
async def job_retry(jid: str) -> dict:
    """Only a failed or stale job runs again: 404 for no such job, 409 for one queued, running or done."""
    try:
        await jobs.retry(jid)
    except KeyError as e:
        raise NotFound("job") from e
    except jobs.RetryRefused as e:
        raise HTTPException(409, f"Only a failed or stale job can be retried; this one is {e.status}.") from e
    return {"ok": True}


# ---------------------------------------------------------------- simulation

@api.post("/pitch/start")
async def pitch_start() -> dict:
    try:
        await engagements.require_confirmed()
    except NotFound as e:
        raise HTTPException(409, "Confirm a source of truth before the simulation: the panel checks every claim "
                                 "against it.") from e
    raise HTTPException(501, "The voice simulation is not built yet. Practice in Preparation meanwhile.")


api.include_router(kb_routes.router)
app.include_router(open_api)
app.include_router(api)


@app.get("/api/v1/{path:path}", include_in_schema=False)
async def _not_found(path: str, request: Request) -> JSONResponse:
    if not auth.token_ok(request.cookies.get(get_settings().cookie_name)):
        return JSONResponse({"detail": "Enter the access code to continue."}, status_code=401)
    return JSONResponse({"detail": f"No route /api/v1/{path}"}, status_code=404)


