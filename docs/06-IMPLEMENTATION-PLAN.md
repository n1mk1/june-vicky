# Vicky — Implementation Plan

Version 1.0 — 17 Oct 2026. Companion to [01-PRD](01-PRD.md), [02-TRD](02-TRD.md), [03-UI-UX](03-UI-UX-DESIGN.md), [04-App flow](04-APP-FLOW.md), [05-Backend schema](05-BACKEND-SCHEMA.md). Budget: about 4–5 build days; demo within 2 weeks on Render.

---

## 0. Prerequisites (user-owned, before Day 1)

| Item | Why | Status |
|---|---|---|
| Anthropic Console API key with billing and a spend limit | No key exists; `ant` CLI not installed | **To do** |
| ElevenLabs key confirmed; 11 voice IDs chosen (10 VCs + Vicky) | Voice per persona | Key available; voices to pick |
| Ask organizers for CSVs 02–10, the xlsx and Appendix J | Only CSV 01 is on disk | To do |
| Decide what the stray file `0` is | Parked in `brand/_unsorted/` | To do |

## 1. Target repository tree

```
june/                      ← repo n1mk1/june-vicky (private)
  README.md  render.yaml  docker-compose.yml  .env.example  .gitignore  .github/workflows/ci.yml
  frontend/                existing app (+ Dockerfile, .dockerignore)
  backend/                 Dockerfile, pyproject.toml, uv.lock, vicky/, migrations/, tests/, evals/,
                           data/{samples/{tidewell,harbor-labs,services-co}, playbooks/, sources.yaml, glossary.yaml, questions.yaml}
  docs/                    01–06 (this set), BACKEND_PLAN.md, VICKY_PLAN.md, ARCHITECTURE.md, design/, challenge/ (gitignored)
  brand/                   vicky/ (logo set), _unsorted/
  .claude/                 skills/clone-website
```

## 2. Schedule

### Day 0 — Reorganize, brand, skeleton, first deploy (4–5 h)

| # | Task | Done when |
|---|---|---|
| 0.1 | **Done 17 Oct.** Move files (nothing deleted): plan → `docs/BACKEND_PLAN.md`; `VICKY_PLAN.md` → `docs/`; brief + PDF → `docs/challenge/` (gitignored); `vickt.png` → `docs/design/wireframe.png`; `logo-format.png`, `trionn-style-prompt.md` → `docs/design/`; `vicky-logo-files/` → `brand/vicky/`; CSV → `backend/data/samples/tidewell/income_statement_monthly.csv` (+ README); `0` → `brand/_unsorted/0.png` | Tree matches §1 |
| 0.2 | **Done 17 Oct.** Fix references: paths in `docs/VICKY_PLAN.md`, `frontend/README.md` (`../vickt.png` → `../docs/design/wireframe.png`), memory note; grep for old paths | `grep` finds none |
| 0.3 | `.gitignore` (`node_modules/`, `.next/`, `.venv/`, `__pycache__/`, `.env*` but not `.env.example`, `docs/challenge/`, `frontend/docs/screenshots/reference/`, `.claude/settings.local.json`, `brand/_unsorted/`, `__MACOSX/`); `git init` in `june/`; initial commit; **confirm with the user**, then `gh repo create n1mk1/june-vicky --private --source . --push` | Repo exists, pushed |
| 0.4 | Brand integration: copy SVGs to `frontend/public/brand/`; `Lockup` uses `June_x_Vicky(.white).svg`; rebuild preloader + 3D mark from the real artwork; favicon/OG from `Vicky_Logo_250x250`; remove `VickyMark.tsx`; re-capture screenshots | Screenshots updated, no `dark:invert` |
| 0.5 | Backend skeleton: `pyproject.toml` (uv), `vicky/api.py` with `/healthz`, `config.py`, `db.py`, `migrate.py` + `0001_init.sql` (all tables in the schema doc), `jobs.py` (arq + inline mode), `auth.py` (gate) | `uv run pytest` green on a hello test |
| 0.6 | Dockerfiles (backend multi-stage with uv; frontend standalone), `.dockerignore`s, `docker-compose.yml` (db, kv, api; profile full: worker, web), `.env.example` | `docker compose --profile full up` serves web + api locally |
| 0.7 | Frontend plumbing: `app/api/v1/[...path]/route.ts` proxy (runtime `API_INTERNAL_URL`, multipart + streaming), `app/api/health`, `lib/api.ts`, `lib/socket.ts`, WS URL passed as a server prop | `/api/v1/healthz` works through the proxy |
| 0.8 | CI workflow (backend, frontend, docker-build) | Green on push |
| 0.9 | `render.yaml` (free: api, web, kv, db; worker commented) → Blueprint sync | First green deploy; `GET /api/v1/healthz` via the web URL returns `{db: ok, kv: ok}` |

Fallback: if `runtime: docker` is refused on the free web plan, move `vicky-api` to `0.5c-512mb` immediately.

### Day 1 — Truth: engagements, canonical model, ingestion, metrics, attack list (9 h)

| # | Task | Done when |
|---|---|---|
| 1.1 | Access gate end to end (`POST /auth/access`, cookie, 401 on routes, rate limit) | FR-14 |
| 1.2 | Engagements + company profile API; one-active-at-a-time rule; new TruthPack → new engagement | Tests |
| 1.3 | `model/canonical.py`, `figures.py` | Types |
| 1.4 | `loader.py`: CSV/XLSX parse, sign/currency normalization, column profiles, wide→long transpose | Tidewell + Harbor Labs parse |
| 1.5 | `mapping.py`: Sonnet `ColumnMapping[]` proposal; confirm/apply; fingerprint reuse. Frontend `MappingTable`, `ProfileForm`, `FactsTable`, `CoverageList`, `SamplePicker`, status pill | Harbor Labs ≥ 90% columns mapped (FR-2) |
| 1.6 | `metrics.py` availability-aware definitions (recurring + generic sets); `coverage.py` | FR-1, FR-3 |
| 1.7 | `sources.yaml` tagged by model/stage + `sources.py` (`cite_source`); `glossary.yaml`; `questions.yaml` | Loaded + validated |
| 1.8 | `truth.py`: `check_claim`, generic attack rules over 12 lenses, forecast-vs-history gaps, deck-claim checker (9 Tidewell claims as a test) | FR-5 |
| 1.9 | TruthPack upload/facts/confirm routes; typed-figure path (Haiku extractor → `founder_stated`) | Confirm produces figures, coverage, attack list |
| 1.10 | PDF/DOCX two-pass citation extraction job + pypdf verification; flagged rows in the UI | FR-7 |
| 1.11 | Fixtures: `pack_facts.yaml`; Harbor Labs and services-co generated by script with seeded numbers; grep test for "Tidewell" | FR-4 |

### Day 2 — Areopagus core, court, Vicky chair, judge, audit (8 h)

| # | Task | Done when |
|---|---|---|
| 2.1 | `llm/client.py` wrapper (effort, parse, fallbacks, refusal, usage → spend, caching breakpoints); `schemas.py` | Unit tests with recorded responses |
| 2.2 | `areopagus/schema.py`, `registry.py` (built-ins from repo, custom from Postgres), `GET/POST/PUT/DELETE /areopagus` | All personas validate |
| 2.3 | Kits: QuantAudit, Customer, Channel, RedTeam, Cash as read-only tools returning Figures | Kit figures match the engine |
| 2.4 | `mind.py` (`write_memo`, `update_and_bid` with the no-concession rule, `speak` streamed + audited, hooks); James, Mark, Alex subclasses | Belief test: cited churn answer lowers confidence; wrong number raises it |
| 2.5 | `court/referee.py` (bid × lane_fit × fairness; follow-up bonus; depth 3; jump-in 0.2; cooldowns) | Referee unit tests with fixed bids |
| 2.6 | `agents/vicky.py` chair step (`ChairDecision`, ≤ 1.5 s, validated, fallback) + coaching mode + debrief | FR-9 |
| 2.7 | `court/session.py` loop; `POST /court/start|answer|end`; memo jobs (parallel, inline on free); AG-UI `/agui/court`; WebSocket hub + Redis pub/sub bridge; reconnect replay | Pub/sub round trip; inline vs worker parity; FR-16 |
| 2.8 | `audit.py` (numbers ±2%, `[src:id]`, valuation blocklist, citations[]); regenerate-once path | FR-6 |
| 2.9 | Judge (dims 2–5 with Appendix D anchors), `scoring.py` (dimension 1 in code), `extractor.py` | Scores persist |
| 2.10 | Tests: 5 seated VCs' first questions hit 5 lenses; James challenges a contradiction; Victor valuation blocked (stub persona) | FR-8 partial |

### Day 3 — Dashboards, Prepare UI wiring, Reports, Areopagus tab (8 h)

| # | Task | Done when |
|---|---|---|
| 3.1 | `viz/spec.py` DSL parser (AST, no eval), `evaluate.py` with provenance + Redis cache, `echarts.py` option builder, `dashboard.py` default layout on confirm | Evaluator matches `lib/tidewell.ts` values; rejects unknown functions/columns/attribute access; option has no LLM values |
| 3.2 | Vicky dashboard tools over `/agui/dashboard` (read tools, `preview_series`, `add/update/remove_widget`, frontend tools); missing-data behaviour | FR-12 backend |
| 3.3 | Frontend: install `echarts`, `@copilotkit/react-core`, `@copilotkit/runtime`, `@ag-ui/client`, `react-grid-layout`; `EChart.tsx`, `echarts-theme.ts`; `WidgetFrame`, `EChartWidget`, `KpiWidget`, `MissingDataTile`, `DashboardGrid`, `DashboardChat`, `ExplainPopover`; `app/api/copilotkit/route.ts`; `lib/dashboard-store.ts`; migrate `TrendChart` and remove `recharts` | Two-tab widget demo; click-to-explain; zoom moves all charts; layout persists (FR-12) |
| 3.4 | Prepare UI wiring: roster from API with Chair card, session setup, memo progress, streamed VC turns with footnotes (`Footnote.tsx`), score/coaching cards, Q&A list from `turns`+`scores`, drills to `founder_memory` | Full Prepare session in the browser |
| 3.5 | Report agent (`report.py` + Vicky synthesis), LLM audit, Sources section, Markdown export; `app/(app)/reports`, `app/report/[id]` | Report renders all 10 sections |
| 3.6 | Areopagus tab: `PersonaCard` grid, fork, import/export | Cards for 3 built-ins + custom |
| 3.7 | `lib/tidewell.ts` → `lib/sample.ts` (offline fallback only); remove Tidewell strings from UI | FR-4 frontend |

### Day 4 — Simulation, voice, remaining VCs, builder, memory, playbooks (8 h)

| # | Task | Done when |
|---|---|---|
| 4.1 | Deck upload + pre-scan job (`deck_reader.py`); pdf.js `PdfSlide`; `DeckDropZone`; gate message; `/pitch/start` 409 | FR-10 |
| 4.2 | `pitch/voice.py`: STT token route, TTS streaming per `voice_id`; browser STT client; Vicky + VC voices | Voice round trip |
| 4.3 | `pitch/session.py`: segments → claims → ledger; live interrupt policy (code candidate, Vicky ≤ 1 s approve/veto, cooldown, per-slide cap, ≤ 2 sentences); after-mode Q&A; delivery stats | FR-11; claim→voice < 3 s |
| 4.4 | Remaining 7 built-ins (Priya, Dana, Kenji, Claire, Victor, Sam, Olivia) + kits (Governance, Market, Terms, Milestone, Benchmark, Product); Kenji ROFR tracking; Claire country switch | FR-8 complete; CA→US changes Claire's questions |
| 4.5 | No-code builder: `POST /areopagus/generate`, `/{id}/test`, `SpecMind`, `PersonaBuilder` sheet with lens sliders, voice picker, templates | FR-13 |
| 4.6 | `memory.py` + `recall`; readiness trend; drill sessions; spaced drills | Report shows delta vs previous |
| 4.7 | Playbooks (`read_playbook`) incl. geo rules marked "verify with an advisor" | Loaded only on relevant topics |

### Day 5 — Evals, hill-climb, polish, demo switch, dry run (5 h)

| # | Task | Done when |
|---|---|---|
| 5.1 | `backend/evals/` self-play harness (prepared / average / evasive / wrong-numbers founders); evals: grounding, distinctness, no-concession, belief direction, chair quality, latency, realism rubric | Thresholds pass |
| 5.2 | Hill-climb persona prompts with the claude-api `hillclimb` flow | Distinctness up, grounding 100% |
| 5.3 | Polish: empty/loading/error states, phone layouts, screenshots re-captured, README (run, deploy, demo switch), `docs/ARCHITECTURE.md` | Checklist in UI/UX §5 covered |
| 5.4 | **Demo-phase switch** (day before judging): dashboard upgrade `vicky-db` → `0.1c-256mb`, `vicky-kv` → `256mb`; commit: api/web → `0.5c-512mb`, uncomment worker, `JOBS_MODE=worker`, `preDeployCommand`, raise `DAILY_USD_BUDGET` | ≈ $37/mo prorated; no cold starts |
| 5.5 | Dry run of the demo path on Render (App flow §10) in two browsers | Every step passes |

## 3. Cut order if behind

1. Drag/resize layout → CSS grid
2. Last 7 built-ins → builder templates
3. Spaced drills (keep the ledger)
4. DOCX/MD intake (keep CSV/XLSX, samples, PDF)
5. Voice previews on cards
6. Live interrupts fall back to typed answers
7. Evals reduced to grounding + no-concession
8. The services fixture (keep Harbor Labs, which proves agnosticism)

**Never cut:** column mapping with founder confirmation, availability-aware metrics, the citation audit.

## 4. Verification checklist

### Automated
- `docker compose --profile full up` → `uv run pytest` and frontend `tsc`/`eslint`/`build` pass; `docker build` both images.
- Backend tests (see TRD §12): Appendix H values on Tidewell; Harbor Labs mapping ≥ 90% and cohort NRR/GRR; services fixture generic-only; CA→US Claire switch; "Tidewell" grep; `check_claim`; audit cases; migration idempotency; pub/sub; inline vs worker parity; DSL parity and rejections; ECharts builder purity; AG-UI event order; missing-data dashboard reply; PDF citation test; 10 personas validate; kit/engine parity; lens coverage; James/Kenji/Victor behaviours; builder round trip; fork keeps method; chair fallbacks; coached time-out purity; self-play thresholds; `/pitch/start` 409; `/api/v1/*` 401.

### Manual on Render
1. Blueprint validates (`render blueprints validate` if installed, else dashboard sync); deploy green; `/api/v1/healthz` → `{db: ok, kv: ok}`.
2. Access code → unfamiliar CSV (Harbor Labs renamed) → profile → mapping → confirm → dashboard with footnotes.
3. Tidewell sample → second engagement; first under Reports.
4. Two tabs: burn-ex-credits widget appears in both; click a bar → formula + rows; zoom moves every chart; drag/resize persists across reload.
5. Prepare with James/Alex/Mark → memos stream → Vicky chairs → weak growth answer → follow-up + time-out → report with Sources.
6. Simulation Live: 3-slide PDF, "growing 10% a month" → VC-voice interruption; ledger `contradicts`. After mode → Q&A + report.
7. "What valuation should we raise at?" → declined with explanation.
8. Redeploy mid-session → WebSocket reconnects, session intact.

## 5. Work-in-parallel notes (if more than one builder or session)

Independent streams after Day 1: (a) Areopagus + court (Day 2), (b) viz + dashboard UI (Day 3.1–3.3), (c) Simulation voice plumbing (Day 4.2). They share only `figures.py`/`metrics.py` interfaces and the WebSocket envelope, which are fixed on Day 1. Writers never touch the same files; frontend streams own `components/<area>/` folders.

## 6. Risk register (delivery)

| Risk | Trigger | Response |
|---|---|---|
| Docker on free web plan refused | Blueprint error | `0.5c-512mb` now |
| CopilotKit/AG-UI hook drift | Install errors on 1.79 | PromptBar + WebSocket fallback |
| react-grid-layout on React 19 | Runtime errors | CSS-grid reorder |
| Opus memo latency on free instance | > 60 s to first question | Reduce effort to medium; cache; show snippets |
| Budget cap hit during a demo rehearsal | 402s | Raise `DAILY_USD_BUDGET` for the day |
| Free Postgres expiry | Day 30 | Upgrade before; it keeps data |
| Voice latency > 3 s | Measured in Day 4.3 | Sentence-chunked TTS; shorter interrupt text; typed fallback |
