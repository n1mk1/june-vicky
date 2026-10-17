# Vicky backend plan: Render (Docker, Postgres, Redis), live dashboards, Vicky + the Areopagus

## Context
`Desktop\june\VICKY_PLAN.md` designs the FastAPI backend (metrics engine, truth layer, VC agents, court, pitch, scoring, reports). The frontend exists in `frontend/` (Next.js 16, Trionn look; real figures in `lib/tidewell.ts`, scripted sessions in `lib/panel.ts`). This plan replaces the plan's infrastructure, dashboard and agent sections. Product logic it doesn't mention stays as written there.

**Decisions made in this conversation**

| Topic | Decision |
|---|---|
| Hosting | Everything on Render, region **Ohio**. Render Postgres is the only database; Render Key Value (Valkey, Redis-compatible) holds ephemeral state. |
| Tier | Free while building; paid plans switched on the day before the demo. **Demo is within 2 weeks**, so the free Postgres (30-day expiry) is created now. |
| Packaging | **Docker everywhere.** Render builds the Dockerfiles from the repo (`runtime: docker`); docker-compose runs the full stack locally. |
| Repo | New private GitHub repo **`n1mk1/june-vicky`** (gh CLI is logged in as n1mk1). Code + sample data; brief, PDF and Trionn reference captures excluded. |
| Identity | **One shared demo workspace** behind an `ACCESS_CODE`. No sign-up. The workspace holds **one company at a time** ("engagement"); confirming a new source of truth starts a new engagement, and earlier ones stay listed under Reports. Custom VCs are workspace-wide. |
| Startup-agnostic | **Tidewell is only the sample and test fixture.** Any founder uploads their own source of truth: CSV/XLSX in any layout (Claude maps columns, founder confirms), PDF/DOCX with page citations, or figures typed in chat. A canonical financial model drives every metric. |
| Business models | **Recurring revenue first:** the full SaaS metric set when recurring revenue is present; otherwise a generic set (revenue, margin, burn, runway, concentration) and VCs probe the gaps. |
| Geography | **Country-aware:** the company profile's country selects tax-credit, government-fund and control-status rules (Canada, US, UK; generic elsewhere), all sourced or flagged "verify with an advisor". |
| Jobs | Separate arq worker fed by a Redis queue (inline in the API on the free tier). |
| Dashboards | **ECharts** charts, **CopilotKit + AG-UI** chat. Claude picks what to chart; code computes every number. |
| Agents | **Vicky** is the lead VC and chair. **10 built-in archetypes** coded in Python on the Anthropic SDK, plus **no-code VCs** from a spec (shared in the workspace). |
| Citations | "Citation first": every figure cites its source; benchmarks only from a sourced library; inline footnotes in the UI; Claude's citations API on uploaded PDFs. |
| Voice | ElevenLabs (key available): realtime STT, one TTS voice per VC and one for Vicky. |
| Claude key | **A Console API key must be created** (none exists; `ant` CLI not installed). Daily spend cap **$5/day** for development, env-configurable; raise for judging. |
| Navigation | 5 tabs: Dashboard · Preparation · Simulation · **Areopagus** · **Reports**. |
| Budget | Full plan, about 4–5 days. |

**Local tooling found:** Docker 29.8 + Compose v5.6, gh 2.101 (logged in), uv 0.11, Python 3.14 (Docker pins 3.13). Render CLI not installed (optional, for `render blueprints validate`). PyPI today: anthropic 1.15.0, ag-ui-protocol 1.0.0, fastapi 0.143, arq 0.28, redis 8.1, asyncpg 0.32, pandas 3.0, pypdf 6.21, elevenlabs 2.73.

## Step 0a: save this plan and organize the project folder (first thing after approval)
**Current state of `Desktop\june`** (a loose folder, untracked inside the Desktop git repo): the product plan, the challenge brief and PDF, a wireframe, brand assets, the Tidewell CSV, the Trionn style prompt, and a stray file named `0`, all at the top level next to `frontend/` and `.claude/`.

**Moves (nothing is deleted; use `git mv` once the repo exists, plain moves before that):**

| From | To | Note |
|---|---|---|
| this plan (`.claude\plans\…`) | `docs/BACKEND_PLAN.md` | Saved as the source of truth for the backend build. |
| `VICKY_PLAN.md` | `docs/VICKY_PLAN.md` | Product plan; its paths and infrastructure sections are updated to match this plan (see Docs to update). |
| `Catalyst - Team 18 Challenge Brief.md`, `ai-pitch-coach-supporting-resources-….pdf` | `docs/challenge/` | **Gitignored** (the brief and PDF stay out of the repo). |
| `vickt.png` | `docs/design/wireframe.png` | |
| `logo-format.png` | `docs/design/logo-format-sheet.png` | |
| `trionn-style-prompt.md` | `docs/design/trionn-style-prompt.md` | |
| `vicky-logo-files/` | `brand/vicky/` | Real brand assets: wordmark, 250×250, lockups (`June_x_Vicky`, `June_slash_Vicky`, stacked, `Vicky_by_June`), SVG + PNG, white variants. |
| `tidewell-data-pack-01-income-statement-monthly-act-….csv` | `backend/data/samples/tidewell/` | Becomes the sample fixture (renamed `income_statement_monthly.csv`; original name kept in a README next to it). |
| `0` (1053×248 PNG, looks blank) | `brand/_unsorted/0.png` | Parked, not deleted. Needs the user's call: likely a white-on-transparent logo export saved with the wrong name. |
| `frontend/docs/screenshots/reference/` (Trionn captures) | stays, **gitignored** | |

**Stays put:** `frontend/` (the app), `.claude/` (the `clone-website` skill; `settings.local.json` is gitignored). The old `june-logo-files-*` folder no longer exists; the June logo already lives at `frontend/public/images/june-logo.png`, and `brand/` becomes its canonical source.

**Target tree**
```
june/                      ← repo n1mk1/june-vicky
  README.md  render.yaml  docker-compose.yml  .env.example  .gitignore  .github/workflows/ci.yml
  frontend/                existing app (+ Dockerfile, .dockerignore)
  backend/                 Dockerfile, pyproject.toml, uv.lock, vicky/, migrations/, tests/, evals/,
                           data/{samples/{tidewell,harbor-labs,services-co}, playbooks/, sources.yaml}
  docs/                    BACKEND_PLAN.md, VICKY_PLAN.md, ARCHITECTURE.md, design/, challenge/ (gitignored)
  brand/                   vicky/ (logo set), _unsorted/
  .claude/                 skills/clone-website
```
**After moving, fix every reference:** the paths inside `VICKY_PLAN.md` (brief, `data/`, `web/`), `frontend/README.md` (`../vickt.png` → `../docs/design/wireframe.png`), the memory note for the June hackathon (plan path now `docs/VICKY_PLAN.md`), and a grep for the old paths across the repo.
**`.gitignore`:** `node_modules/`, `.next/`, `.venv/`, `__pycache__/`, `.env*` (but not `.env.example`), `docs/challenge/`, `frontend/docs/screenshots/reference/`, `.claude/settings.local.json`, `brand/_unsorted/`, `__MACOSX/`.
**Git:** `git init` inside `june/` (a nested repo, separate from the Desktop repo), initial commit of the organized tree, then `gh repo create n1mk1/june-vicky --private --source . --push`. Pushing publishes the code to a private GitHub repo, so I'll confirm right before that step.

**Brand integration (follows the reorg, before day 1):** the provided logos supersede the placeholder VICKY mark I drew.
- Copy the needed SVGs into `frontend/public/brand/`.
- `Lockup` uses `June_x_Vicky.svg` in light mode and `June_x_Vicky_white.svg` in dark mode, so the manual `dark:invert` goes away.
- The preloader and the 3D landing mark are rebuilt from the real VICKY artwork (extruding the wordmark's sliced "K"/"Y" or the V from `Vicky_Logo.svg`). `components/ui/VickyMark.tsx` and its polygons are removed once nothing uses them.
- Update the favicon and Open Graph image from `Vicky_Logo_250x250`.
- Re-capture the page screenshots afterwards.

## Principles (enforced in code, not just prompts)
1. **Numbers come from code.** The metrics engine computes every figure. Agents only choose what to compute, cite and chart.
2. **Citation first.** A `Figure` is `{id, value, unit, formula, inputs[], source: {kind: csv|pdf|pack_summary|benchmark, ref: row range | page | url}, kind: historical|forecast|founder_claim}`. Any number in agent output must resolve to a Figure (±2%) or be quoted back as founder-said; otherwise the deterministic audit blocks the text and the turn is regenerated once with the audit feedback. Benchmarks exist only through `cite_source` from `backend/data/sources.yaml` (curated entries with URLs). Uploaded PDFs are extracted with Claude's citations API so each fact carries page-level `cited_text`, which code re-verifies against the PDF text. The UI renders footnotes; reports end with a Sources section.
3. **Agents are stateless per call.** Memos, beliefs, turns and claims live in Postgres; every call is rebuilt from them. Thinking blocks are never replayed.
4. **No valuation or investment advice.** Pattern blocklist in the audit, applied to every VC, Vicky and the report.
5. **Missing data is reported as missing.** Coverage checklist on the TruthPack; VCs treat gaps as questions.
6. **Nothing is hard-coded to one company.** No metric, threshold, question or UI string may reference Tidewell; the sample is loaded through the same path as any upload. A second synthetic fixture in the test suite enforces this.

## Startup-agnostic design
**Engagement** = one company's workspace state: `company_profiles` (name, country, currency, fiscal year start, stage, round type/size, business model `recurring | other`, data granularity month/quarter), its TruthPack, datasets, dashboards, sessions, reports and founder memory, all keyed by `engagement_id`. Vicky collects the profile in chat on first upload (or infers and asks to confirm); "Use the Tidewell sample" fills it in one click.

**Canonical financial model** (`vicky/model/canonical.py`): a fixed vocabulary of fields, each with unit and period granularity: revenue (`recurring`, `one_time`, `total`), `cogs`, `gross_profit`, opex by category (`r_and_d`, `s_and_m`, `g_and_a`, `customer_success`, `other`), `headcount` (by function), `cash_balance`, `net_income`, `non_dilutive_income` (tax credits/grants), customers (`count`, `new`, `churned`), `bookings`, `pipeline`; optional tables: per-customer MRR, cohorts, cap table. Currency and sign conventions (`$1,234`, `(5,000)`, `-$5`) are normalized once in the loader.

**Any-layout ingestion** (`loader.py` + `mapping.py`): parse CSV/XLSX → column profiles (name, dtype, sample values, detected period axis; wide layouts with months as columns are transposed) → Sonnet 5.5 structured output `ColumnMapping[]{source_column, canonical_field, unit, confidence}` → **founder confirms or edits the mapping** in a table UI (low-confidence rows highlighted; unmapped columns kept as raw dataset columns the dashboard DSL can still chart) → stored in `dataset_mappings` and reused on re-upload. PDF/DOCX facts map to the same fields through the citation pipeline. Typed figures in chat ("our MRR is $80K, burn $40K") go through the Haiku claim extractor into pending facts with source `founder_stated`; VCs treat those as claims, not records.

**Metrics by availability:** every metric definition declares the canonical fields it needs. With inputs present it returns a `Figure`; otherwise a `MissingFigure{needs[], reason}` that feeds the coverage checklist ("Upload a cohort table to unlock NRR/GRR"). The recurring-revenue set (ARR, MRR growth, NRR/GRR, CAC payback, burn multiple, magic number) activates when `recurring` revenue exists; the generic set (revenue growth, gross margin, burn, runway, concentration, opex mix) always runs.

**Generic attack list** (`truth.py`): rules over metrics, each tagged with a lens and a sourced threshold from `sources.yaml` (growth deceleration, runway below the stage norm, top-customer share, GRR/NRR below norms, burn multiple, forecast-vs-history gaps, deck claims that contradict the model, missing data). Deck claims are extracted generically from any deck (numeric and factual claims) and checked against the model; the "9 Tidewell claims" become a test case.

**Benchmarks by model and stage:** `sources.yaml` entries carry `business_model`, `stage` and `as_of`; `cite_source` filters by the profile; when nothing matches, the agent says no sourced benchmark exists rather than inventing one.

**Country-aware rules:** `playbooks/geo/{CA,US,UK,generic}.md` and the Governance kit switch on `company_profile.country` (Canada: SR&ED, CCPC status; US: R&D credit, SBIR; UK: R&D relief); the government-fund archetype (Claire) becomes "government-backed / mandate-driven fund" and reads the country rules. Everything is marked "verify with an advisor".

**Fixtures:** `backend/data/samples/tidewell/` (CSV 01 + pack facts, as today) and a second synthetic company `harbor-labs/` (US SaaS, quarterly, wide layout, different column names, no tax credits, a cohort table) used by tests and available as a second sample. A third tiny non-recurring fixture (`services-co`) exercises the generic metric set.

**Frontend:** no Tidewell strings; the header pill shows the engagement's company name and TruthPack status; the landing hint offers "Try a sample"; `lib/tidewell.ts` becomes `lib/sample.ts` (offline fallback only); a mapping-confirm screen is added to the TruthPack flow; Reports lists past engagements.

## Architecture
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
- **vicky-web:** Next.js `output: "standalone"` in Docker. `/api/v1/*` is a route-handler proxy that reads `API_INTERNAL_URL` at runtime (no build args needed; supports multipart and streaming). The public WebSocket URL is read server-side at request time and passed to the client as a prop, so nothing is baked in at build.
- **vicky-api:** FastAPI + uvicorn. REST, uploads, one multiplexed WebSocket per tab (`/ws?session=…`), and AG-UI endpoints for Vicky's chat in each mode. Latency-critical work stays here (dashboard turns, CSV/XLSX parsing, claim checks, chair step, live interrupts, VC speech streaming).
- **vicky-worker:** same image, `dockerCommand: uv run arq vicky.jobs.WorkerSettings`. Runs memos, deck pre-scan, PDF/DOCX extraction, reports + LLM audit, persona generation. `JOBS_MODE=inline` runs the same arq worker inside the API's lifespan on the free tier.
- **Postgres** is the only durable store: the `VICKY_PLAN.md` tables plus `engagements`, `company_profiles`, `jobs`, `uploads` (bytea, 10 MB cap: Render has no free disk), `datasets`, `dataset_mappings`, `dashboards`, `widgets`, `dashboard_messages`, `vc_personas`, `founder_memory`, `sources`. Everything company-specific is keyed by `engagement_id`.
- **Redis** (ephemeral only, so free-tier data loss is harmless): arq queue (`noeviction`), pub/sub channels `vicky:session:{id}` and `vicky:dashboard:{id}`, pitch hot state (`vicky:pitch:{id}`, 6h TTL), computed-series cache keyed by spec hash, rate limit `vicky:rl:{ip}` and daily spend `vicky:spend:{date}`.
- **Access gate:** `ACCESS_CODE` entered once on the landing page → HTTP-only signed cookie; every API route except `/healthz` requires it. Rate limit per IP and the daily USD budget guard LLM-spending routes.

## Docker setup
**Repo layout:** see the target tree in Step 0a (`render.yaml`, `docker-compose.yml` and CI at the root; `backend/` and `frontend/` each with a Dockerfile and `.dockerignore`; docs under `docs/`, brand files under `brand/`).
**`backend/Dockerfile`** (one image for api and worker): multi-stage on `python:3.13-slim`; uv copied from `ghcr.io/astral-sh/uv:0.11` (pinned); `uv sync --frozen --no-dev` into a venv layer before copying source (layer cache); non-root user; `ENV PYTHONUNBUFFERED=1`; `CMD ["uv","run","uvicorn","vicky.api:app","--host","0.0.0.0","--port","10000","--ws-ping-interval","20"]` with the port overridden by `$PORT` through a tiny `entrypoint.sh`.
**`frontend/Dockerfile`:** `node:22-alpine` multi-stage: `npm ci` → `npm run build` with `output: "standalone"` → runtime stage copies `public`, `.next/standalone`, `.next/static`; `ENV HOSTNAME=0.0.0.0`; **no hardcoded PORT** (Render sets `PORT`; Next's standalone server reads it); `CMD ["node","server.js"]`. Note: Render doesn't keep `.next/cache`, so builds are cold; acceptable.
**`.dockerignore`** per service: `node_modules`, `.next`, `.venv`, `__pycache__`, `tests`/`evals` (backend runtime image), `docs/`, `.env*`.
**`docker-compose.yml`** (local): `db` (`postgres:17`, volume), `kv` (`valkey/valkey:8`), `api` (build `./backend`, mounts source, `--reload`, `JOBS_MODE=inline`, env from `.env`), `worker` (profile `full`), `web` (profile `full`: build target `dev`, mounts source, `next dev`). `docker compose up db kv` for infra only; `docker compose --profile full up` for the whole stack. Local URLs: `DATABASE_URL=postgresql://vicky:vicky@db:5432/vicky`, `REDIS_URL=redis://kv:6379`.
**`render.yaml`** (Docker runtime; paths are repo-root-relative and `rootDir` is **not** used, which sidesteps the docs' disagreement about rootDir-relative Docker paths):
- `vicky-api`: `type: web`, `runtime: docker`, `dockerfilePath: ./backend/Dockerfile`, `dockerContext: ./backend`, `buildFilter.paths: [backend/**, render.yaml]`, `healthCheckPath: /healthz`, `maxShutdownDelaySeconds: 60`, `autoDeployTrigger: checksPass`. Env: `DATABASE_URL` (fromDatabase connectionString), `REDIS_URL` (fromService keyvalue connectionString), `JOBS_MODE`, `WEB_ORIGIN`, `DAILY_USD_BUDGET=5`, secrets `sync: false`: `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ACCESS_CODE`, `COOKIE_SECRET` (`generateValue: true`).
- `vicky-worker`: `type: worker`, same Dockerfile/context, `dockerCommand: uv run arq vicky.jobs.WorkerSettings`, same env. Present in the file, commented out in the free phase (workers have no free plan).
- `vicky-web`: `type: web`, `runtime: docker`, `dockerfilePath: ./frontend/Dockerfile`, `dockerContext: ./frontend`, `buildFilter.paths: [frontend/**, render.yaml]`, `healthCheckPath: /api/health`. Env: `API_INTERNAL_URL` from `vicky-api` `hostport`, `API_PUBLIC_WS_URL` (`sync: false`, set after first deploy).
- `vicky-kv`: `type: keyvalue`, `plan: free`, `ipAllowList: []`, `maxmemoryPolicy: noeviction`.
- `databases: vicky-db`: `plan: free`, `postgresMajorVersion: '17'`, `databaseName: vicky`, `user: vicky`.
- Migrations: on free, run at API startup under `pg_advisory_lock`; on paid, `preDeployCommand: uv run python -m vicky.migrate`.
- **Fallback:** the docs don't state that `runtime: docker` is allowed on the free web plan. If the Blueprint refuses it, put `vicky-api` on `0.5c-512mb` ($7/mo, prorated) immediately rather than maintaining a native-runtime variant.
**Secrets:** `.env` locally (gitignored, `.env.example` committed); Render env vars for deploy; no secret files; never `ARG` secrets.
**CI** (`.github/workflows/ci.yml`): backend job (uv sync, ruff, pytest with Postgres + Valkey service containers), frontend job (npm ci, tsc, eslint, build), docker-build job (both images, no push). Render auto-deploys on `main` when checks pass.

**Demo-phase switch (day before judging):** Dashboard: upgrade `vicky-db` → `0.1c-256mb` (keeps data), `vicky-kv` → `256mb`. Commit: api and web → `0.5c-512mb`, uncomment `vicky-worker`, `JOBS_MODE=worker`, add `preDeployCommand`, raise `DAILY_USD_BUDGET`. About $37/mo prorated; downgrade after.

## Citation pipeline
1. **Figures.** `metrics.py` returns `Figure`s with formula, inputs and source refs (CSV row range or pack-fact page). `check_claim` returns the Figure it compared against.
2. **PDF/DOCX facts (worker job).** PDF → Files API upload → `messages.create` with the `document` block, `citations: {enabled: true}`, asking for facts one per line in a fixed format (citations are incompatible with `output_config.format`, so this pass is free text). Pass 2: `messages.parse()` turns pass-1 text + its citation objects into `Fact[]{name, value, unit, period, kind, page, cited_text}`. Code verifies `cited_text` occurs on that page via pypdf; unverifiable facts are flagged for the founder in the confirm table. DOCX/MD: extracted text goes through the same two passes with char-offset citations.
3. **Benchmarks.** `cite_source(topic)` returns `{source_id, claim, url, as_of}` from `sources.yaml`; the audit requires any benchmark phrase to carry a `[src:id]` token. Seeded entries: Sacks burn multiple, SaaStr Series A metrics, Bessemer growth, Paul Graham default-alive, BDC seed mandate, a16z metric definitions. Entries the research marked secondary/outdated (SR&ED limits) stay out until checked.
4. **Agent output → footnotes.** The audit maps each number to its Figure and each `[src:id]` to its source and attaches `citations[]` to the message. The frontend renders superscript markers with a hover card (formula, inputs, source row/page/URL) and an "open source" action. Reports end with a numbered Sources section.
5. **Dashboards.** Every plotted point keeps `{value, formula, inputs, source}`; click-to-explain shows it.

## Vicky: the lead VC who runs the Areopagus
Vicky is the one voice the founder always talks to: the managing partner who chairs the panel. The 10 archetypes are her partners. She doesn't grade; an independent Judge agent does.

| Where | Vicky's job |
|---|---|
| Landing / Dashboard chat | Answers questions about the numbers, builds and edits dashboards (the dashboard tools are hers), routes the founder to Prepare or Simulate with a reason. |
| Prepare court | Sets the agenda from the attack list and the founder's goals, seats and introduces the panel, chairs each turn (who speaks, with what intent, on which hypothesis), can interject (end a thread, switch topic, coaching time-out), closes with a debrief. |
| Simulation | Rules on live interrupts: code proposes a candidate, Vicky approves or vetoes within 1 s (code decides alone on timeout). Runs the post-pitch Q&A. |
| Areopagus builder | Turns a description into a `VCPersona` and suggests kits. |
| Report | Writes the synthesis and action plan; Judge scores and audit stay independent. |

**Chair step** (after each founder answer, after the parallel belief updates/bids): Sonnet 5.5, low effort, structured output `ChairDecision{action: call_on|interject|end_session, vc_id?, intent, hypothesis_id?, note?}` over the bids, open hypotheses, ledger, goals, budgets and a referee-computed candidate list (cooldowns, fairness, depth cap, jump-in margin). The referee validates; invalid or late (>1.5 s) decisions fall back to the top code-ranked candidate. Every decision and reason is logged for the report.
**Coaching mode** per session: Realistic (default in Simulation: silent until debrief) or Coached (default in Prepare: after two weak answers on one hypothesis, a short time-out that names the gap and points at the Figure without answering).
**Code:** `agents/vicky.py` with toolsets per mode (chair: `call_on/interject/switch_topic/end_thread`; dashboard widget tools; read-only kits; `recall`; `create_vc`), loaded through tool search. Opus 5.5 for chat/debrief, Sonnet 5.5 low for the chair step. AG-UI: Vicky's text streams as her messages, VC turns as messages tagged with the VC id, chair decisions as state deltas (drive the speaking dot).
**Frontend:** fixed "Chair" card at the top of every roster (VICKY mark glyph, not deselectable); coaching time-outs as inline cards; landing and dashboard chat are always Vicky.

## Making the agents genuinely good (vs prepping in plain Claude)
| Edge | What a plain chat can't do | How we build it |
|---|---|---|
| Ground truth | Checks founder numbers against their own data, live | Typed read-only tools returning Figures; audit-then-regenerate; `check_claim` mid-pitch |
| Ten hidden agendas | Distinct investors with private memos and beliefs that move only on evidence | Per-VC kits, coded methods, separate stateless calls; **no-concession rule** enforced in the belief update (concern drops only when the answer cites a matching Figure) |
| Memory over time | "Last session you said 10%" and spaced drills | `founder_memory` tables (weakness ledger by lens, past answers + scores, rewrites seen, drills done) exposed as `recall(topic)`; readiness trend from it |
| Real rehearsal | Voice, deck-aware interrupts, delivery stats | ElevenLabs STT/TTS, deck pre-scan, per-slide talk time, filler words |
| Expert playbooks | Curated knowledge, loaded only when relevant | `backend/data/playbooks/*.md` (metric traps, term-sheet mechanics, SR&ED/CCPC basics marked "verify", deck heuristics, per-archetype question banks with Appendix D anchors) via `read_playbook(topic)` — skills-style progressive disclosure without a container, so live turns stay fast. Real Agent Skills + code execution reserved for the optional worker-side deep dive. |
| Sourced benchmarks | No invented norms | `cite_source` only |
| Actionable feedback | Independent scores, cited strong-answer rewrites, "why this was asked", drill list | Judge agent on Opus 5.5 with rubric anchors; report agent |
| Live dashboards | Charts of their own data for the questions coming | ECharts + Vicky's dashboard tools |

**Engineering practice:** short concrete persona cards (role, what they optimize for, signature move, 3 example exchanges, dealbreakers; no over-specified rules); cached stable prefix (tools → rules → persona); effort per route (memos high, chair/bids low, speech medium); structured outputs everywhere a machine reads; server-side fallbacks (`fallbacks: "default"`) on Opus/Sonnet; `stop_reason`/`refusal` checked before reading content; few precise tools with recoverable error messages; unit tests for every kit tool.
**Self-play harness** (`backend/evals/`): scripted founder agents (prepared, average, evasive, wrong-numbers) run full sessions. **Evals:** grounding (100% numbers match a Figure), distinctness (blind judge identifies the archetype; confusion matrix), no-concession, belief movement direction, chair quality (lens coverage, repetition, depth), latency (P50 answer→first token < 3 s), realism (human rubric on 10 transcripts). Built with the claude-api `build-eval` flow; prompts improved with `hillclimb`.
**Cost guard:** `DAILY_USD_BUDGET` in Redis (estimated from `usage` per call at list prices), max 5 seated VCs, memos cached per TruthPack + persona version, `count_tokens` on the largest prompts. Rough cost: a Prepare session with 3 VCs ≈ $2–2.5 (memos ~$0.3, ~$0.2/turn, report ~$0.3), so $5/day ≈ 2 sessions; raise before judging.

## The Areopagus: VC agents
**SDK:** Anthropic Python SDK 1.x (async): `client.beta.messages.tool_runner` + `@beta_async_tool`; `messages.parse()` for structured outputs; `output_config.effort`; adaptive thinking (`display: "summarized"` where snippets are shown); prompt caching breakpoints after tools+system and after the persona block. Models: Opus 5.5 memos/judge/report/Vicky chat; Sonnet 5.5 belief-bid/speech/chair/persona-gen; Haiku 5.5 claim extraction and intent routing. **Not** the Claude Agent SDK (Node subprocess per agent, file/bash tools, too heavy for 512 MB instances and <3 s turns) nor Managed Agents (per-session containers; our code referee owns the turn order).

**Layers** (`backend/vicky/areopagus/`)
1. `schema.py` — `VCPersona`: `id, name, archetype, bio, cheque_role, priorities{lens: weight}` over 12 lenses (claims, forecast, retention, unit_economics, concentration, runway, governance, market, team, product_tech, terms_cap_table, impact), `style{tone, interrupt_tendency, follow_up_depth, aggression}`, `signature_move, question_seeds[], dealbreakers[], scoring_weights, voice_id, base_archetype?, kits[], builtin`.
2. `kits/` — deterministic analyses exposed as read-only `@beta_async_tool`s returning Figures: `QuantAudit` (ARR without fees, cohort NRR/GRR, burn multiple, CAC payback incl. support, runway sensitivity), `Customer` (concentration, churn events, rep ramp), `Channel` (partner revenue share, data-rights checklist), `Governance` (finance function, SR&ED treatment, board, IP location), `RedTeam` (stress scenarios: growth keeps decaying, largest customer leaves, forecast vs history), `Market` (TAM claims vs sourced figures), `Terms` (dilution and waterfall math from founder inputs; never valuation advice), `Milestone` (use-of-funds vs milestones), `Benchmark` (metric vs `cite_source`), `Cash` (default-alive test, fatal-pinch date), `Product` (services revenue share, custom-work signals).
3. `mind.py` — `VCMind`: `write_memo()` (thesis, 3–5 weakness hypotheses with Figure evidence, mind-changers, opening question), `update_and_bid(answer)`, `speak(intent)` streamed and audited; override hooks `memo_method`, `choose_target`, `follow_up_policy`, `on_answer`.
4. `builtin/<archetype>.py` + `.yaml` — one subclass per archetype with its method in the hooks.
5. `custom.py` — `SpecMind(VCMind)` for no-code VCs: driven by the spec; kits chosen from lenses; `base_archetype` inherits that built-in's hooks (fork keeps the method).
6. `registry.py` — built-ins from the repo, custom from Postgres `vc_personas`, both schema-validated; `GET/POST/PUT/DELETE /areopagus`, `POST /areopagus/generate`.

**Runtime:** memos = one arq job per seated VC in parallel (Opus 5.5 high; summarized-thinking snippets via pub/sub: "Mark is stress-testing growth…"); belief/bid in the API in parallel (Sonnet low); referee pure code; speech streamed over AG-UI (chat tab) and WebSocket (other tabs).

**Built-in roster (10).** James, Alex and Mark keep their UI slots; default panel stays James, Alex, Mark; max 5 seated. Interrupt/depth values are starting points.

| VC | Archetype | Main lens → secondary | Kits | Method (signature move) | Int / depth |
|---|---|---|---|---|---|
| James | Lead seed partner | team, forecast → claims, runway | Milestone, QuantAudit | *Lines, not dots:* `on_answer` compares with earlier answers and deck claims (across sessions) and challenges drift; closes asking for 3 measurable milestones for the round | 0.4 / 3 |
| Mark | Skeptical IC partner | concentration, claims → forecast, retention | RedTeam | *Pre-mortem chain* in `memo_method`: failure stories → stress scenarios → the one weakest claim; "so what?" follow-ups | 0.8 / 3 |
| Priya | Series A readiness | retention, unit_economics → forecast, claims | QuantAudit, Benchmark | *Benchmark comparison* via `cite_source` only; decomposes net new ARR into new/expansion/churn | 0.6 / 2 |
| Dana | Capital-efficiency hawk | runway, unit_economics → forecast | Cash | *Rebuilds the cash model live:* burn multiple, default-alive, fatal-pinch date under the founder's downside; non-dilutive bridges | 0.7 / 3 |
| Alex | Operator angel (ex-CRO) | claims, concentration (channel) → team | Customer, Channel | *Stories before numbers:* last lost deal / churned customer, then the figure; who owns renewals with the partner | 0.5 / 2 |
| Kenji | Corporate / strategic VC | product_tech, market, terms → governance | Channel, Terms | *Trap terms:* floats ROFR / exclusivity / data side letter; `on_answer` tracks whether the founder noticed | 0.3 / 2 |
| Claire | Government-backed / mandate-driven fund (country-aware) | governance, impact → runway, terms | Governance | *Mandate audit:* dependence on tax credits or grants, control-status rules, local hiring/IP, co-investors, reporting; rules come from the profile's country playbook; questions only, never tax advice | 0.2 / 2 |
| Victor | Term-sheet tactician | terms_cap_table, governance → claims | Terms | *Floats an aggressive term* and makes the founder compute their own outcome; audit blocks valuation recommendations | 0.5 / 3 |
| Sam | Technical / product diligence | product_tech, claims → concentration | Product | *Hardest feature, not slickest:* custom work for the anchor customer, SR&ED story vs product story, IP, security | 0.4 / 3 |
| Olivia | Market / power-law visionary | market, forecast → claims | Market | *"How big can this be?"* bottom-up market size tied back to today's 5% growth | 0.3 / 2 |

Excluded (offered as builder templates): impact/ESG fund (no thesis for Tidewell; Claire covers impact), family office (overlaps James/Dana), accelerator partner (folded into James's milestones), revenue-based lender (folded into Dana). `truth.py` ranks the attack list across all 12 lenses; gap ownership splits items among the seated VCs.

**No-code builder** (Areopagus tab, and the roster's "+"): describe in natural language → `POST /areopagus/generate` (Sonnet structured output), or pick a template (any built-in or excluded archetype) → edit form (name/archetype/cheque role; lens-weight sliders that pick kits; tone/interrupt/depth sliders; dealbreaker and seed chips; signature move; voice picker) → "How would they open?" test memo against the current TruthPack → save (shared in the workspace). Edit/duplicate/delete for custom; built-ins read-only but forkable. YAML/JSON import/export for the "through code" path. Guardrails: spec text in a delimited persona block treated as character description; field caps; audit applies to every VC.
**Optional stretch:** Lead Seed deep dive via code execution + a custom Agent Skill over the TruthPack CSVs (Files API), memo phase only; any number it produces must reconcile with a metrics-engine Figure before it can be spoken.

## Live dashboards (ECharts + CopilotKit/AG-UI)
1. **Input → TruthPack.** PromptBar attach → `POST /api/v1/uploads` (10 MB, bytea). CSV/XLSX parsed inline by `loader.py` into `datasets`, then the column-mapping step (Claude proposes, founder confirms); PDF/DOCX → worker extraction with citations; typed figures → `founder_stated` facts. Founder confirms the facts table (existing gate; unverifiable citations flagged). Vicky asks for the company profile the first time. Landing chat: create session → upload → Haiku intent (`data`/`dashboard` → `/dashboard?session=…`, `practice` → `/preparation`).
2. **Default dashboard** (`dashboard.py`): on confirm, the wireframe layout (margin ring, ARR card, readiness orb — stays React Three Fiber — trend chart) plus the `VICKY_PLAN.md` chart set where the data supports it; otherwise a missing-data tile naming the upload needed.
3. **`vicky/viz/`:** `spec.py` `WidgetSpec{template: line|area|bar|stacked_bar|combo_bar_line|waterfall|kpi|gauge_ring|heatmap|scatter|table, title, series[{ref: metric id | DSL expr}], window, group_by, compare, presentation{stack, smooth, dual_axis, labels, mark_lines, sort, unit}}`; DSL = `+ − × ÷`, `sum avg rolling cmgr pct_of yoy mom cumsum lag`, parsed to an AST, no `eval`. `evaluate.py` computes series with per-point provenance (Redis-cached). `echarts.py` builds the full ECharts option (`dataset.source`, `dataZoom` inside+slider, shared `axisPointer`, `brush`, theme names not colours). The LLM never touches `dataset`.
4. **Vicky's dashboard tools over AG-UI** (`/agui/dashboard`, `ag-ui-protocol` encoder as `StreamingResponse`): read tools (`list_datasets/list_columns/list_metrics/get_metric`), `preview_series(spec)`, `add_widget/update_widget/remove_widget`; frontend tools `set_time_range`, `focus_widget`, `highlight_series`; generative-UI "Widget added" cards with Undo. Missing data → says what's missing, adds nothing.
5. **Realtime:** `dashboards.version` optimistic concurrency; diffs published on `vicky:dashboard:{id}`; all tabs apply via WebSocket; chat tab also gets AG-UI state deltas (store dedupes by version). New upload/edited fact recomputes affected widgets.
6. **Interaction:** linked tooltips (`echarts.connect`), dataZoom/brush → dashboard-wide time range, legend toggles, click-to-explain popover, drag/resize/remove/pin via react-grid-layout 2.x persisted by `PATCH /dashboards/{id}/layout`, "Ask about this" → `useCopilotReadable`.
**Frontend:** add `echarts`, `@copilotkit/react-core`, `@copilotkit/runtime`, `@ag-ui/client`, `react-grid-layout`; remove `recharts` after migrating `TrendChart`. New: `components/charts/EChart.tsx` (own ~40-line wrapper over `echarts/core`), `lib/echarts-theme.ts` (`vicky-dark`/`vicky-light` from the CSS tokens), `components/dashboard/{WidgetFrame,EChartWidget,KpiWidget,MissingDataTile,DashboardGrid,DashboardChat}`, `app/api/copilotkit/route.ts`, `app/api/v1/[...path]/route.ts` proxy, `lib/{api,socket,dashboard-store}.ts`, `components/ui/Footnote.tsx`. New tabs: `app/(app)/areopagus` (cards + builder), `app/(app)/reports` (engagements + reports list) and `app/report/[id]`; a `components/truth/MappingTable.tsx` confirm screen and a company-profile form in the TruthPack flow. Header pill shows the company name and TruthPack status. Mocks stay as offline fallback when `API_INTERNAL_URL` is unset.

## Build order (about 4–5 days)
| Day | Work | Hours |
|---|---|---|
| 0 | Step 0a (save plan, reorganize folders, fix references, `.gitignore`, git init); brand integration (real logos in the frontend); prerequisites: Console API key (billing + spend limit), confirm ElevenLabs key; `gh repo create n1mk1/june-vicky --private` (confirm before pushing); skeleton, Dockerfiles, compose, CI, `.env.example`; Blueprint applied (free), first green deploy of a hello API + web; `/healthz` through the proxy | 4–5 |
| 1 | Access gate; engagements + company profile; canonical model; any-layout loader + column mapping (Claude proposal + confirm UI); `figures/metrics/truth` with availability-aware metrics and sources; `sources.yaml` tagged by model/stage; TruthPack upload/confirm (CSV/XLSX + both samples, then PDF citations two-pass + verification, typed facts); coverage checklist; generic attack list over 12 lenses; tests on both fixtures | 9 |
| 2 | Areopagus core: schema, kits (QuantAudit, Customer, Channel, RedTeam, Cash), `VCMind`, James/Mark/Alex; referee; Vicky chair + coaching; court API + AG-UI `/agui/court` + WebSocket; Judge, audit (numbers, benchmarks, no-valuation), scoring; tests | 8 |
| 3 | Dashboards: viz spec/evaluator/echarts, default layout, Vicky dashboard tools, CopilotKit route, grid, realtime; frontend wiring for Prepare (court, roster, Q&A, footnotes); Reports tab + report agent + Sources section; Areopagus tab (cards) | 8 |
| 4 | Simulation: deck pre-scan, ElevenLabs STT/TTS (Vicky + VC voices), live interrupts, after-mode Q&A; remaining 7 built-ins + kits (Governance, Market, Terms, Milestone, Benchmark, Product); no-code builder; founder memory + drills; playbooks | 8 |
| 5 | Evals + self-play, hillclimb the persona prompts, polish, demo-phase switch, dry run with the Tidewell sample end-to-end on Render | 5 |

**Cut order if behind:** (1) drag/resize layout → CSS grid; (2) last 7 built-ins → builder templates; (3) spaced drills (keep the ledger); (4) DOCX/MD intake; (5) voice previews on cards; (6) live interrupts fall back to typed answers; (7) evals reduced to grounding + no-concession; (8) the services fixture (keep Harbor Labs, which proves agnosticism). **Never cut:** column mapping with founder confirmation, availability-aware metrics, the citation audit.

## Risks and mitigations
| Risk | Mitigation |
|---|---|
| `runtime: docker` refused on the free plan | Put `vicky-api` on `0.5c-512mb` at once (prorated $7) |
| Free API spins down (~1 min cold start) during judging | Switch to paid the day before; landing page pings `/healthz` on load |
| Free Postgres expires after 30 days | Created now (demo within 2 weeks); upgrade keeps data |
| Free Key Value loses queued jobs on restart | Stale `jobs` rows show Retry; nothing durable in Redis |
| Citations API incompatible with structured outputs | Two-pass extraction + code verification of `cited_text` |
| Opus memos slow or costly | Parallel jobs, cached per TruthPack + persona version, budget guard |
| Forced `tool_choice` unsupported on 5.5 models | `auto` + `strict: true` + prompt steering; structured outputs where only JSON is needed |
| CopilotKit/AG-UI hook names drift | Verify `@copilotkit/*` 1.79 headless hooks and `HttpAgent` at install; fallback is our PromptBar + WebSocket |
| react-grid-layout on React 19 | Unverified in official notes; fallback CSS-grid reorder |
| Thinking blocks and edited history (preserved thinking) | Stateless rebuild; never replay thinking; append-only transcripts |
| Missing CSVs 02–10 | `pack_facts.yaml` from the appendices, labelled "data pack summary"; coverage gaps become VC questions |
| Shared workspace: one founder's actions affect everyone | One engagement at a time; confirming a new TruthPack starts a new engagement rather than merging; access code limits who's in |
| Column mapping guesses wrong | Founder confirms every mapping; low-confidence rows highlighted; unmapped columns stay available as raw data; mappings reused on re-upload |
| Unusual data (no monthly series, non-recurring model) | Availability-aware metrics return `MissingFigure`; generic metric set always runs; typed-figure path as a last resort |
| Country rules wrong or stale | Only sourced rules ship; everything else is a question marked "verify with an advisor"; generic playbook for unsupported countries |

## Verification
- **Local:** `docker compose --profile full up` → `uv run pytest` (in the api container or host) and the frontend checks pass; `docker build` both images.
- **Tests (backend):** on the Tidewell fixture, metrics match Appendix H (ARR $1.29M, growth 9.0%/5.0%, margins 92%/78%, burn $58.4K); on the Harbor Labs fixture (quarterly, wide layout, different column names), the mapping proposal maps ≥ 90% of columns correctly, metrics compute, cohort-based NRR/GRR appear, and tax-credit figures report as missing; on the services fixture only the generic set runs and the SaaS metrics are `MissingFigure`s; switching the profile country from CA to US changes Claire's kit questions and the geo playbook; a grep test asserts no "Tidewell" string outside `data/samples/` and tests; `check_claim("churn", 1%)` contradicts; audit flags "NRR is 115%" and "raise at a $20M valuation" and uncited benchmarks; migration idempotency; pub/sub round trip; inline vs worker job parity; DSL evaluator values match `lib/tidewell.ts` and rejects unknown functions/columns/attribute access; ECharts builder output contains no LLM-supplied values; AG-UI event order; dashboard agent returns "missing" with no widget for churn cohorts without CSV 05; PDF extraction: a short PDF stating "MRR $107,189 Sep 2026" yields a fact with page 1 and verified `cited_text`; all 10 personas validate; kit figures match the engine; 5 seated VCs' first questions hit 5 different lenses; James challenges a contradicting answer; Kenji records a missed ROFR; Victor's valuation reply is blocked and regenerated; builder description → valid persona → test question → saved and visible to another browser in the workspace; forking Mark keeps the pre-mortem; `ChairDecision` breaking a cooldown or arriving after 1.5 s falls back to the code pick; Coached mode time-out contains no new figure; self-play suite passes grounding, no-concession and distinctness thresholds; `/pitch/start` 409 without a confirmed TruthPack; `/api/v1/*` 401 without the access cookie.
- **Manual on Render (free, then demo phase):** blueprint validates (`render blueprints validate` if the CLI is installed; otherwise the dashboard's Blueprint sync); deploy green; `GET /api/v1/healthz` via the web URL returns `{db: ok, kv: ok}`; enter the access code; upload an unfamiliar CSV (e.g. the Harbor Labs sample renamed) on the landing page → Vicky asks for the company profile, the mapping screen shows the proposal, confirm → dashboard appears with footnoted figures; then "Use the Tidewell sample" starts a second engagement and the first stays under Reports; in two tabs, ask Vicky for "burn excluding SR&ED as % of revenue by quarter" → widget in both tabs, click a bar shows formula + source rows; "zoom to the last 6 months" moves every chart; drag/resize persists across reload; Prepare with James/Alex/Mark → memos stream, Vicky chairs, a weak growth answer gets a follow-up and (Coached) a time-out, report with Sources renders; Simulation Live: 3-slide PDF, say "growing 10% a month" → interruption in a VC voice, ledger shows `contradicts`; After mode → Q&A + report; ask "what valuation should we raise at?" → declined with an explanation; redeploy mid-session → WebSocket reconnects, session intact.

## Open items
- **Prerequisites the user does:** create the Anthropic Console key (with billing and a spend limit), provide the ElevenLabs key, pick 11 voice IDs (10 VCs + Vicky), ask organizers for CSVs 02–10 / xlsx / Appendix J.
- **Fixtures to author:** the synthetic Harbor Labs company (quarterly, wide layout, cohort table) and the tiny services company; generated by script with seeded numbers so expected metrics are known.
- **Verify when installing:** CopilotKit 1.79 headless hooks and `HttpAgent` import; AG-UI Python event classes; react-grid-layout 2.x on React 19; `fromService … type: keyvalue, property: connectionString` in the Blueprint; Docker on the free web plan; custom Agent Skill upload (stretch only).
- **Docs to update:** rewrite the infrastructure, dashboard, Areopagus and build-order sections of `docs/VICKY_PLAN.md` to match this plan; add `docs/ARCHITECTURE.md` and a root `README.md` (run, deploy, demo switch).
- **Needs the user's call:** what the stray file `0` is (kept parked in `brand/_unsorted/` until then).