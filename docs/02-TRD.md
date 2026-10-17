# Vicky — Technical Requirements Document (TRD)

Version 1.0 — 17 Oct 2026. Companion to [01-PRD](01-PRD.md). Source decisions: [BACKEND_PLAN.md](BACKEND_PLAN.md).

---

## 1. Decisions at a glance

| Topic | Decision |
|---|---|
| Hosting | Render, region Ohio. Render Postgres (only durable store), Render Key Value (Valkey, Redis-compatible) for ephemeral state |
| Tier | Free while building; paid plans the day before the demo. Free Postgres (30-day expiry) created now |
| Packaging | Docker everywhere. Render builds Dockerfiles (`runtime: docker`); docker-compose runs the stack locally |
| Repo | Private GitHub repo `n1mk1/june-vicky`. Code + sample data; brief, PDF and Trionn reference captures gitignored |
| Backend | Python 3.13, FastAPI + uvicorn, asyncpg, pandas, pypdf, arq (jobs), uv (packaging) |
| Frontend | Next.js 16 (App Router, `output: "standalone"`), React 19, Tailwind v4, React Three Fiber, ECharts, CopilotKit + AG-UI, react-grid-layout 2.x |
| LLM | Anthropic Python SDK 1.x (async). Opus 5.5 memos/judge/report/Vicky chat; Sonnet 5.5 belief-bid/speech/chair/persona-gen/mapping; Haiku 5.5 claim extraction + intent routing |
| Voice | ElevenLabs realtime STT; one TTS voice per VC and one for Vicky |
| Identity | One shared workspace behind `ACCESS_CODE` → signed HTTP-only cookie |
| Jobs | arq worker on a Redis queue; `JOBS_MODE=inline` runs the worker inside the API on the free tier |
| Budget | `DAILY_USD_BUDGET` (default 5) enforced in Redis from per-call `usage` |

**Local tooling present:** Docker 29.8 + Compose v5.6, gh 2.101 (logged in as n1mk1), uv 0.11, Python 3.14 host (Docker pins 3.13). PyPI versions at planning time: anthropic 1.15.0, ag-ui-protocol 1.0.0, fastapi 0.143, arq 0.28, redis 8.1, asyncpg 0.32, pandas 3.0, pypdf 6.21, elevenlabs 2.73.

## 2. System architecture

```
                     browser (any number of tabs)
      ┌────────────────┬────────────────────────┐
      │ HTTPS           │ AG-UI SSE (chat tab)    │ WSS (all tabs)
vicky-web (Next.js, Docker)                      │
  /api/copilotkit → CopilotKit runtime ──private──▶ vicky-api (FastAPI, Docker)
  /api/v1/[...path] route-handler proxy ─private─▶   REST · /ws · /agui/{dashboard,court,pitch}
                                                     ├── Render Postgres  vicky-db
                                                     └── Render Key Value vicky-kv ◀─ queue/pubsub ─▶ vicky-worker (arq, same image)
```

### 2.1 Services

| Service | Type | Image | Responsibilities |
|---|---|---|---|
| `vicky-web` | Render web | `frontend/Dockerfile` (node:22-alpine, standalone) | UI; `/api/v1/*` proxy reading `API_INTERNAL_URL` at runtime (multipart + streaming); `/api/copilotkit` CopilotKit runtime; `/api/health` |
| `vicky-api` | Render web | `backend/Dockerfile` (python:3.13-slim + uv) | REST, uploads, one multiplexed WebSocket per tab (`/ws?session=…`), AG-UI endpoints; latency-critical work (dashboard turns, CSV/XLSX parsing, claim checks, chair step, live interrupts, VC speech streaming); migrations at startup under `pg_advisory_lock` on free tier |
| `vicky-worker` | Render worker | same image, `uv run arq vicky.jobs.WorkerSettings` | Memos, deck pre-scan, PDF/DOCX extraction, reports + LLM audit, persona generation. Commented out in the free phase |
| `vicky-db` | Render Postgres 17 | — | Only durable store |
| `vicky-kv` | Render Key Value | `maxmemoryPolicy: noeviction` | arq queue, pub/sub, pitch hot state, series cache, rate limit, spend counter |

### 2.2 Backend package layout (`backend/vicky/`)

```
vicky/
  api.py                FastAPI app, routers, lifespan (inline worker when JOBS_MODE=inline)
  config.py             pydantic-settings (env)
  auth.py               access-code gate, cookie signing, rate limit, budget guard
  db.py  migrate.py     asyncpg pool; SQL migrations in backend/migrations/
  jobs.py               arq WorkerSettings + job functions
  realtime.py           WebSocket hub, Redis pub/sub bridge, AG-UI encoders
  model/
    canonical.py        canonical field vocabulary (units, granularity)
    loader.py           CSV/XLSX parse → column profiles; sign/currency normalization; wide→long transpose
    mapping.py          Sonnet mapping proposal → ColumnMapping[]; confirm/apply
    figures.py          Figure / MissingFigure dataclasses
    metrics.py          availability-aware metric definitions → Figure
    truth.py            attack list over 12 lenses; check_claim; forecast-vs-history gaps; deck claims
    coverage.py         coverage checklist
    sources.py          cite_source over data/sources.yaml (filtered by business_model/stage)
    truthpack.py        ingest → facts → confirm; engagement lifecycle
    documents.py        PDF/DOCX two-pass citation extraction + pypdf verification
  viz/
    spec.py             WidgetSpec, DSL parser → AST (no eval)
    evaluate.py         series evaluation with per-point provenance (Redis-cached by spec hash)
    echarts.py          ECharts option builder (dataset.source filled by code only)
    dashboard.py        default layout on confirm; widget CRUD; version/concurrency
  llm/
    client.py           SDK wrapper: effort, parse(), fallbacks, stop_reason/refusal checks, usage → spend
    schemas.py          pydantic outputs (Memo, BeliefUpdate, ChairDecision, Claim, Fact, Report, VCPersona…)
    prompts/            cached stable prefixes
  agents/
    vicky.py            Vicky: dashboard tools, chair step, coaching, debrief, builder, report synthesis
    judge.py  report.py  extractor.py  deck_reader.py  auditor_llm.py  persona_gen.py  intent.py
  areopagus/
    schema.py           VCPersona
    kits/               QuantAudit, Customer, Channel, Governance, RedTeam, Market, Terms, Milestone, Benchmark, Cash, Product
    mind.py             VCMind: write_memo, update_and_bid, speak; override hooks
    builtin/            <archetype>.py + .yaml (10)
    custom.py           SpecMind for no-code VCs
    registry.py         built-ins from repo, custom from Postgres
  court/
    referee.py          pure-code candidate ranking, cooldowns, fairness, depth cap, jump-in margin
    session.py          Prepare loop
  pitch/
    session.py          deck pre-scan, transcript segments, ledger, interrupt policy, after-mode Q&A
    voice.py            ElevenLabs STT token issuing, TTS streaming per voice_id
  audit.py              deterministic audit: numbers ±2%, [src:id] benchmarks, valuation blocklist → citations[]
  scoring.py            dimension 1 in code; aggregates
  memory.py             founder_memory read/write, recall(topic)
  playbooks.py          read_playbook(topic) over data/playbooks/*.md and geo/{CA,US,UK,generic}.md
```

## 3. Data model and metrics engine

### 3.1 Figure (the atomic unit)

```python
class Figure(BaseModel):
    id: str                       # e.g. "arr", "cmgr_12m"
    label: str
    value: float
    unit: Literal["cad","usd","gbp","pct","months","count","ratio","x"]
    formula: str                  # human-readable, e.g. "Sep 26 subscription revenue × 12"
    inputs: list[FigureRef]       # other figures or dataset cells
    source: Source                # {kind: csv|xlsx|pdf|docx|pack_summary|founder_stated|benchmark, ref: row range | page | url, dataset_id?}
    kind: Literal["historical","forecast","founder_claim","benchmark"]
    period: str | None            # "2026-09", "2026-Q3", "L12M"

class MissingFigure(BaseModel):
    id: str
    needs: list[str]              # canonical fields required
    reason: str                   # "Upload a cohort table to unlock NRR/GRR"
```

### 3.2 Canonical financial model (`model/canonical.py`)

Fixed vocabulary, each field with unit and period granularity: revenue (`recurring`, `one_time`, `total`), `cogs`, `gross_profit`, opex by category (`r_and_d`, `s_and_m`, `g_and_a`, `customer_success`, `other`), `headcount` (by function), `cash_balance`, `net_income`, `non_dilutive_income`, customers (`count`, `new`, `churned`), `bookings`, `pipeline`; optional tables: per-customer MRR, cohorts, cap table. Sign and currency conventions (`$1,234`, `(5,000)`, `-$5`) normalized once in the loader.

### 3.3 Ingestion (`loader.py` + `mapping.py`)

1. Parse CSV/XLSX → column profiles `{name, dtype, sample_values, detected_period_axis}`; wide layouts (months as columns) transposed.
2. Sonnet 5.5 structured output → `ColumnMapping[]{source_column, canonical_field, unit, confidence}`.
3. Founder confirms/edits in the MappingTable UI; stored in `dataset_mappings`, reused on re-upload (matched by column-name fingerprint).
4. Unmapped columns remain raw dataset columns available to the DSL.

### 3.4 Metrics by availability (`metrics.py`)

Each metric declares the canonical fields it needs. With inputs present it returns a `Figure`; otherwise a `MissingFigure`. Recurring set activates when `recurring` revenue exists: ARR, MRR growth (CMGR over windows), NRR/GRR (needs cohort table), CAC and payback (needs S&M + new customers; margin includes customer success), burn multiple (net burn ÷ net new ARR), magic number. Generic set always: revenue growth, gross margin (booked and incl. support), burn (net loss excluding non-dilutive income), runway (needs cash), concentration (needs per-customer MRR), opex mix.

Target values on the Tidewell fixture (Appendix H / I): ARR $1.29M; MRR $107,189; CMGR ≈ 9%/12 mo, ≈ 5% recent; GM 92% booked, 74% L12M incl. CS; burn ≈ $58K/mo; runway ≈ 8 mo; burn multiple 0.6 (0.8 ex-SR&ED); CAC ≈ $3,200, payback 9–10 mo; churn 2.0%/1.6%; NRR ≈ 88%, GRR ≈ 81%; Northern Comfort ≈ 10% of MRR.

### 3.5 Truth layer (`truth.py`)

- `check_claim(metric, value, unit, period?) → {status: matches|contradicts|unsupported|forecast_as_fact, figure}` with ±2% tolerance (configurable per metric).
- Generic attack rules, each tagged with a lens and a sourced threshold from `sources.yaml`: growth deceleration, runway below stage norm, top-customer share, GRR/NRR below norms, burn multiple, forecast-vs-history gaps (rep ramp, churn, price rise, unsigned expansion), deck claims contradicting the model, missing data.
- Deck claims are extracted generically from any deck; the nine Tidewell claims become a test case.

### 3.6 Benchmarks (`sources.py`, `data/sources.yaml`)

Curated entries `{id, claim, url, publisher, as_of, business_model, stage, topic}`. `cite_source(topic)` filters by the company profile; no match → the agent says no sourced benchmark exists. Seeded: Sacks burn multiple, SaaStr Series A metrics, Bessemer growth, Paul Graham default-alive, BDC seed mandate, a16z metric definitions. Secondary/outdated entries (SR&ED limits) excluded until checked.

### 3.7 Country-aware rules

`data/playbooks/geo/{CA,US,UK,generic}.md` selected by `company_profile.country`. Canada: SR&ED, CCPC status; US: R&D credit, SBIR; UK: R&D relief. Everything marked "verify with an advisor". Claire's kit reads these.

## 4. Citation pipeline

1. **Figures** carry formula, inputs and source refs (CSV row range or pack-fact page). `check_claim` returns the Figure it compared against.
2. **PDF/DOCX facts (worker job):** Files API upload → `messages.create` with a `document` block and `citations: {enabled: true}`, asking for facts one per line (citations are incompatible with `output_config.format`). Pass 2: `messages.parse()` turns pass-1 text + citation objects into `Fact[]{name, value, unit, period, kind, page, cited_text}`. Code verifies `cited_text` occurs on that page via pypdf; failures flagged in the confirm table. DOCX/MD use char-offset citations.
3. **Benchmarks** only via `cite_source`; the audit requires `[src:id]` on any benchmark phrase.
4. **Agent output → footnotes:** the audit maps each number to its Figure and each `[src:id]` to its source, attaching `citations[]` to the message. Frontend renders superscripts with a hover card (formula, inputs, source) and an "open source" action. Reports end with a Sources section.
5. **Dashboards:** every plotted point keeps `{value, formula, inputs, source}` for click-to-explain.

## 5. Agents

### 5.1 SDK usage rules (`llm/client.py`)

- `client.beta.messages.tool_runner` + `@beta_async_tool` for tool loops; `messages.parse()` for structured outputs; `output_config.effort` per route; adaptive thinking with `display: "summarized"` where snippets are shown.
- Prompt caching breakpoints after tools+system and after the persona block (stable → volatile order: tools → rules/glossary/Appendix D anchors → persona + memo → beliefs, recent turns, intent).
- Thinking cannot be disabled on Opus/Sonnet 5.5; depth controlled by `effort`. Forced `tool_choice` unsupported → `auto` + `strict: true` + steering; structured outputs where only JSON is needed.
- `stop_reason` (incl. `refusal`) checked before reading content. Server-side fallbacks (`fallbacks: "default"`) on Opus/Sonnet.
- Every call is stateless: rebuilt from Postgres; thinking blocks never replayed; transcripts append-only.
- Usage per call → estimated USD at list prices → `vicky:spend:{date}`; over budget → LLM routes return 402 with a clear message.
- Not used: Claude Agent SDK (subprocess per agent; too heavy for 512 MB and < 3 s turns) and Managed Agents (our referee owns turn order).

### 5.2 Roster

| Agent | Model / effort | Shape | Output |
|---|---|---|---|
| VC memo | Opus 5.5, high | tool_runner with read-only kit tools, then parse | `Memo{thesis, hypotheses[{id, claim, lens, evidence[figure_id], severity, confidence}], mind_changers[], opening_question}` |
| VC update + bid | Sonnet 5.5, low | one parse per VC per answer, all parallel | `BeliefUpdate{deltas[{hyp_id, new_confidence, why}], bid, intent: follow_up|new_topic|jump_in|pass, target_hyp}` |
| VC speak | Sonnet 5.5, medium | streaming, tools `get_metric`, `check_claim`, `cite_source`, `read_playbook`, `recall` | question text in persona style |
| Vicky chair | Sonnet 5.5, low | parse ≤ 1.5 s | `ChairDecision{action: call_on|interject|end_session, vc_id?, intent, hypothesis_id?, note?}` |
| Vicky chat / debrief / builder / report synthesis | Opus 5.5, medium–high | tool_runner (dashboard tools, `create_vc`, `recall`) over AG-UI | streamed messages + state deltas |
| Claim extractor | Haiku 5.5, low | parse | `Claim[]{text, metric, value, unit, period, is_forecast}` |
| Intent router | Haiku 5.5, low | parse | `data|dashboard|practice|other` |
| Column mapper | Sonnet 5.5, medium | parse | `ColumnMapping[]` |
| Deck reader (pre-scan) | Opus 5.5, medium | `document` block + slide text + TruthPack summary | `SlideFinding[]{slide, claims[], visual_issues[], omissions[]}` |
| Doc fact extractor | Opus 5.5, medium | two-pass citations | `Fact[]` |
| Judge | Opus 5.5, high | parse, independent of VCs | scores dims 2–5, rationale, good/missing, strong-answer rewrite |
| Report writer | Opus 5.5, high | streaming + parse | `Report` (10 sections) |
| Auditor (LLM half) | Sonnet 5.5, low | parse; reports + persona generation only | `AuditFinding[]` |
| Persona generator | Sonnet 5.5, medium | parse | `VCPersona` |

### 5.3 Tools (all read-only, `strict: true`)

`get_metric(name, window?)`, `list_metrics()`, `check_claim(metric, value, unit, period?)`, `get_attack_list(lens?)`, `forecast_gaps()`, `list_missing_data(topic)`, `define_term(term)`, `cite_source(topic)`, `read_playbook(topic)`, `recall(topic)`; kit tools per archetype; simulation-only `get_slide(n)`, `get_transcript(window)`, `get_ledger()`; Vicky-only dashboard tools `list_datasets/list_columns/list_metrics/get_metric/preview_series(spec)/add_widget/update_widget/remove_widget`, chair tools `call_on/interject/switch_topic/end_thread`, builder `create_vc`. Loaded through tool search per mode.

### 5.4 The Areopagus

- `schema.py` `VCPersona{id, name, archetype, bio, cheque_role, priorities{lens: weight} over 12 lenses, style{tone, interrupt_tendency, follow_up_depth, aggression}, signature_move, question_seeds[], dealbreakers[], scoring_weights, voice_id, base_archetype?, kits[], builtin}`.
- `kits/` deterministic analyses returning Figures: QuantAudit, Customer, Channel, Governance, RedTeam, Market, Terms (dilution/waterfall math only, never valuation), Milestone, Benchmark, Cash (default-alive, fatal-pinch date), Product.
- `mind.py` `VCMind.write_memo() / update_and_bid(answer) / speak(intent)` with override hooks `memo_method`, `choose_target`, `follow_up_policy`, `on_answer`. **No-concession rule** in `update_and_bid`: confidence on a hypothesis can only drop when the answer cites a Figure matching it.
- `builtin/<archetype>.py` one subclass per archetype (James lines-not-dots, Mark pre-mortem chain, Priya benchmark comparison, Dana live cash model, Alex stories-before-numbers, Kenji trap terms, Claire mandate audit, Victor aggressive-term, Sam hardest-feature, Olivia how-big). Default panel James, Alex, Mark; max 5 seated.
- `custom.py` `SpecMind` driven by the spec; kits chosen from lenses; `base_archetype` inherits hooks.
- Guardrails: persona text inside a delimited block treated as character description; field caps; audit on every VC.

### 5.5 Court turn loop

1. Session start: memos in parallel (one arq job per VC; inline on free tier); snippets over pub/sub; gap ownership assigns attack-list items by lens weight (severity ≥ 0.8 may be shared).
2. Founder answer stored → parallel: claim extraction + `check_claim` (accuracy score), Judge, every VC `update_and_bid`.
3. Referee (pure code): candidates ranked by `bid × lane_fit × fairness_decay(turns_since_spoke)`; follow-up bonus when the answer was weak; depth cap 3; jump-in margin 0.2; cooldowns.
4. Chair step: Sonnet low over bids, open hypotheses, ledger, goals, budgets and the candidate list → `ChairDecision`; referee validates; invalid or > 1.5 s → top code candidate. Every decision logged.
5. Speak: streamed over AG-UI (chat tab) and WebSocket (other tabs); sentence chunker → deterministic audit → TTS (optional in Prepare). Audit failure → regenerate once with feedback → fallback to memo `opening_question`.
6. Coaching: Coached mode time-out after two weak answers on one hypothesis (names the gap, points at the Figure, adds no figure).
7. End conditions: question cap (6–20), time cap, all hypotheses resolved (< 0.2 or > 0.8), founder ends. Then report job + LLM audit.

### 5.6 Simulation pipeline

Setup: deck pre-scan job seeds the ledger; memos include deck findings. Presenting: STT final segments tagged with slide → Haiku claims → `check_claim` → ledger → UI. Live mode: candidate = `severity × interrupt_tendency × lane_fit` in code; Vicky approve/veto ≤ 1 s; 30 s cooldown; ≤ 1 per slide; ≤ 2 sentences; founder answers by voice; Judge; resume. After mode: transcript + ledger → chaired Q&A (6–8). Delivery stats from transcript timing (talk time per slide, fillers, dodges).

### 5.7 Audit (`audit.py`)

Regex-extract every number; normalize units ($, K, M, %, months, x); each must match a Figure within ±2% or be a quoted founder statement; `[src:id]` required on benchmark phrases; valuation/investment-advice blocklist; emits `citations[]`. Applies to every VC, Vicky, coaching card and report.

## 6. Live dashboards

- `viz/spec.py` `WidgetSpec{template: line|area|bar|stacked_bar|combo_bar_line|waterfall|kpi|gauge_ring|heatmap|scatter|table, title, series[{ref: metric id | DSL expr}], window, group_by, compare, presentation{stack, smooth, dual_axis, labels, mark_lines, sort, unit}}`.
- DSL: `+ − × ÷`, `sum avg rolling cmgr pct_of yoy mom cumsum lag`, parsed to an AST; unknown functions/columns/attribute access rejected; no `eval`.
- `evaluate.py` computes series with per-point provenance; cached in Redis by spec hash; invalidated when a dataset or fact changes.
- `echarts.py` builds the full option (`dataset.source`, `dataZoom` inside + slider, shared `axisPointer`, `brush`, theme names). The LLM never supplies values.
- Realtime: `dashboards.version` optimistic concurrency; diffs on `vicky:dashboard:{id}`; all tabs apply via WebSocket; chat tab also gets AG-UI state deltas (store dedupes by version).
- Frontend: `components/charts/EChart.tsx` (~40-line wrapper over `echarts/core`), `lib/echarts-theme.ts` (`vicky-dark` / `vicky-light` from CSS tokens), widgets `WidgetFrame`, `EChartWidget`, `KpiWidget`, `MissingDataTile`, `DashboardGrid` (react-grid-layout; CSS-grid fallback), `DashboardChat` (CopilotKit headless hooks; fallback is PromptBar + WebSocket). `recharts` removed after `TrendChart` migrates.

## 7. Realtime protocols

| Channel | Transport | Payload |
|---|---|---|
| `/agui/dashboard`, `/agui/court`, `/agui/pitch` | SSE (`ag-ui-protocol` encoder as `StreamingResponse`) | AG-UI events: `RUN_STARTED`, `TEXT_MESSAGE_*` (Vicky and VC messages tagged with speaker id), `TOOL_CALL_*`, `STATE_DELTA` (chair decisions, widget diffs, ledger), `RUN_FINISHED` |
| `/ws?session=…` | WebSocket, one per tab, ping 20 s | `{type, session_id, version, payload}`: `vc.turn.delta`, `vc.turn.done`, `chair.decision`, `memo.snippet`, `ledger.update`, `widget.diff`, `job.status`, `interrupt`, `coach.timeout` |
| Redis pub/sub | `vicky:session:{id}`, `vicky:dashboard:{id}` | same envelope; API fan-out to sockets |

Reconnect: client resumes with `since_version`; server replays from Postgres (turns, widgets) so a redeploy mid-session loses nothing.

## 8. API surface (REST, under `/api/v1`, cookie-gated except `/healthz`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/access` | Exchange access code for cookie |
| GET | `/healthz` | `{db: ok, kv: ok}` |
| GET/POST | `/engagements`, `/engagements/{id}/profile` | List; create/update company profile |
| POST | `/uploads` | Multipart ≤ 10 MB → `uploads` row; triggers parse or extraction job |
| GET/PUT | `/datasets/{id}/mapping` | Proposed mapping; confirm/edit |
| GET/POST | `/truth`, `/truth/facts`, `/truth/confirm` | Pending facts; edit; confirm → attack list, coverage, default dashboard, new engagement |
| GET | `/metrics`, `/metrics/{id}`, `/attack-list`, `/coverage` | Figures |
| GET/PATCH | `/dashboards/{id}`, `/dashboards/{id}/layout` | Dashboard + widgets; layout persistence |
| POST | `/dashboards/{id}/widgets/preview` | Evaluate a spec without saving |
| GET/POST/PUT/DELETE | `/areopagus`, `/areopagus/{id}` | Personas (custom writable; built-ins read-only) |
| POST | `/areopagus/generate`, `/areopagus/{id}/test` | NL → persona preview; "How would they open?" |
| POST | `/court/start`, `/court/{id}/answer`, `/court/{id}/end` | Prepare sessions (settings: panel, question cap, coaching mode) |
| POST | `/pitch/start` (409 without confirmed TruthPack), `/pitch/{id}/segment`, `/pitch/{id}/end` | Simulation |
| POST | `/voice/stt-token` | Short-lived ElevenLabs token |
| GET | `/voice/tts?text=&voice_id=` | Streamed audio |
| GET | `/sessions/{id}/report`, `/reports`, `/reports/{id}.md` | Reports |
| GET | `/jobs/{id}` | Job status; stale rows show Retry |

## 9. Security, limits and cost

- Access gate: `ACCESS_CODE` → signed cookie (`COOKIE_SECRET`, generated by Render); every route but `/healthz` requires it; 401 otherwise.
- Rate limit per IP (`vicky:rl:{ip}`); daily USD budget guard on LLM routes.
- Secrets only via env (`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ACCESS_CODE`, `COOKIE_SECRET`); never `ARG` in Dockerfiles; `.env` gitignored, `.env.example` committed.
- Uploads ≤ 10 MB, bytea in Postgres (Render has no free disk).
- ElevenLabs key never reaches the browser; STT uses short-lived tokens.
- Persona spec text is data, never instructions.

## 10. Docker, Render and CI

- `backend/Dockerfile`: multi-stage on `python:3.13-slim`; uv from `ghcr.io/astral-sh/uv:0.11`; `uv sync --frozen --no-dev` before copying source; non-root; `PYTHONUNBUFFERED=1`; `entrypoint.sh` maps `$PORT`; CMD uvicorn with `--ws-ping-interval 20`.
- `frontend/Dockerfile`: `node:22-alpine` multi-stage; `npm ci` → `next build` (standalone) → runtime copies `public`, `.next/standalone`, `.next/static`; `HOSTNAME=0.0.0.0`; no hardcoded PORT; `CMD ["node","server.js"]`.
- `docker-compose.yml`: `db` (postgres:17), `kv` (valkey:8), `api` (reload, `JOBS_MODE=inline`), profile `full`: `worker`, `web` (`next dev`). `docker compose up db kv` or `docker compose --profile full up`.
- `render.yaml` (no `rootDir`; repo-root-relative paths): `vicky-api` web/docker with `healthCheckPath: /healthz`, `maxShutdownDelaySeconds: 60`, `autoDeployTrigger: checksPass`, `buildFilter` on `backend/**`; `vicky-worker` (commented out on free); `vicky-web` with `API_INTERNAL_URL` from `vicky-api` hostport and `API_PUBLIC_WS_URL` set after first deploy; `vicky-kv` keyvalue free, `ipAllowList: []`; `databases: vicky-db` free, Postgres 17.
- Fallback: if `runtime: docker` is refused on the free web plan, move `vicky-api` to `0.5c-512mb` immediately.
- CI (`.github/workflows/ci.yml`): backend (uv sync, ruff, pytest with Postgres + Valkey service containers), frontend (npm ci, tsc, eslint, build), docker-build (both images, no push). Render auto-deploys `main` on green.
- Demo switch (day before judging): `vicky-db` → `0.1c-256mb`, `vicky-kv` → `256mb`, api and web → `0.5c-512mb`, uncomment worker, `JOBS_MODE=worker`, `preDeployCommand: uv run python -m vicky.migrate`, raise `DAILY_USD_BUDGET`. ≈ $37/mo prorated; downgrade after.

## 11. Environment variables

| Var | Service | Notes |
|---|---|---|
| `DATABASE_URL` | api, worker | fromDatabase |
| `REDIS_URL` | api, worker | fromService keyvalue |
| `JOBS_MODE` | api | `inline` (free) / `worker` |
| `WEB_ORIGIN` | api | CORS + cookie domain |
| `DAILY_USD_BUDGET` | api, worker | default 5 |
| `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ACCESS_CODE`, `COOKIE_SECRET` | api, worker | `sync: false` |
| `API_INTERNAL_URL`, `API_PUBLIC_WS_URL` | web | read at request time, never baked at build |

## 12. Testing and evals

- Unit/integration (`backend/tests/`): metrics on three fixtures; mapping accuracy; `check_claim`; audit cases; migration idempotency; pub/sub round trip; inline vs worker parity; DSL evaluator parity with `lib/tidewell.ts` values and rejection of unsafe expressions; ECharts builder contains no LLM-supplied values; AG-UI event order; persona validation; kit figures match the engine; referee and chair fallbacks; gate and auth codes; grep test for "Tidewell".
- Self-play harness (`backend/evals/`): scripted founders (prepared, average, evasive, wrong-numbers). Evals: grounding 100%, distinctness confusion matrix, no-concession, belief direction, chair quality (lens coverage, repetition, depth), latency P50 < 3 s, realism rubric on 10 transcripts. Built with the claude-api `build-eval` flow; prompts improved with `hillclimb`.
- Frontend: tsc, eslint, build; Playwright screenshot script for every page in both themes.
- Manual on Render: see the verification list in the implementation plan.

## 13. Technical risks

| Risk | Mitigation |
|---|---|
| `runtime: docker` refused on free plan | `0.5c-512mb` at once |
| Free API cold start (~1 min) during judging | Paid tier the day before; landing pings `/healthz` on load |
| Free Postgres expires in 30 days | Created now; upgrade keeps data |
| Free Key Value loses queued jobs | Stale `jobs` rows show Retry; nothing durable in Redis |
| Citations API incompatible with structured outputs | Two-pass extraction + pypdf verification |
| Opus memos slow or costly | Parallel jobs; cached per TruthPack + persona version; budget guard |
| Forced `tool_choice` unsupported on 5.5 | `auto` + `strict` + steering; structured outputs |
| CopilotKit/AG-UI hook drift | Verify `@copilotkit/*` 1.79 headless hooks and `HttpAgent` at install; fallback PromptBar + WebSocket |
| react-grid-layout on React 19 | Verify; fallback CSS-grid reorder |
| Preserved-thinking edited-history 400s | Stateless rebuild; never replay thinking; append-only transcripts |
