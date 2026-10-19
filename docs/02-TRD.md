# Vik — Technical Requirements Document (TRD)

Version 1.1 — 19 Oct 2026 (1.0: 17 Oct 2026). Companion to [01-PRD](01-PRD.md); the REST contract as built is [API.md](API.md).

---

## 1. Decisions at a glance

| Topic | Decision |
|---|---|
| Hosting | Render, region Ohio. Render Postgres (only durable store), Render Key Value (Valkey, Redis-compatible) for ephemeral state. Both were created before the Blueprint and are wired in by connection string (IDs in the `render.yaml` header), not declared in it |
| Tier | Free while building; paid plans the day before the demo. Free Postgres created 2026-10-18; it expires 2026-11-17 unless upgraded |
| Packaging | Docker everywhere. Render builds Dockerfiles (`runtime: docker`); docker-compose runs the stack locally |
| Repo | GitHub repository `n1mk1/vik` (public). Code + sample data; brief, PDF and Trionn reference captures gitignored |
| Backend | Python 3.13, FastAPI + uvicorn, asyncpg, pandas, pypdf, arq (jobs), uv (packaging) |
| Frontend | Next.js 16 (App Router, `output: "standalone"`), React 19, Tailwind v4, React Three Fiber, ECharts, react-grid-layout 2.x |
| LLM | Google Gemini through the Google Gen AI Python SDK (`google-genai` ≥ 2.31, async `client.aio`). The defaults are free-tier models, spread over three so each has its own per-model quota. Gemini 3.8 Flash: Vik's court routes (chair, line review, scoring, knowledge probes and verification), document facts, column mapping, Ask Vik, the organizer, profile autofill, persona drafts, pitch-vs-notes ratings; Gemini 3.6 Flash: the investors (memo, belief update + bid, speech, knowledge questions); Gemini 3.5 Flash-Lite: claim extraction, pitch statements, answers from retrieved notes and the catch-all. On a paid key, `MODEL_VIK` / `MODEL_DEEP` can be set to Gemini 4 Argon (not on the free tier) |
| Voice | ElevenLabs realtime STT; one TTS voice per VC and one for Vik |
| Identity | One shared workspace behind `ACCESS_CODE` → signed HTTP-only cookie |
| Jobs | arq worker on a Redis queue; `JOBS_MODE=inline` runs the worker inside the API on the free tier |
| Budget | `GEMINI_TIER=free` (default, a free AI Studio key): calls cost nothing and no dollar budget applies; each model is paced to `GEMINI_RPM` requests a minute and rests after a 429. `GEMINI_TIER=paid`: `DAILY_USD_BUDGET` (default 5; 20 on Render) enforced from each response's `usage_metadata`: a reservation before every call, settled after, on a counter kept in Redis and in the Postgres `spend` table |

**Local tooling present:** Docker 29.8 + Compose v5.6, gh 2.101 (logged in as n1mk1), uv 0.11, Python 3.14 host (Docker pins 3.13). PyPI versions at planning time: ag-ui-protocol 1.0.0, fastapi 0.143, arq 0.28, redis 8.1, asyncpg 0.32, pandas 3.0, pypdf 6.21, elevenlabs 2.73; `google-genai` 2.31.0 is locked since the move to Gemini (19 Oct 2026).

## 2. System architecture

```
                     browser (any number of tabs)
      ┌──────────────────────────────────────────┐
      │ HTTPS                                    │ WSS (all tabs)
vik-web (Next.js, Docker)                        │
  /api/v1/[...path] route-handler proxy ─────────▶ vik-api (FastAPI, Docker)
                                                     REST · /ws
                                                     ├── Render Postgres 17 (pgvector)
                                                     └── Render Key Value ◀─ queue/pubsub ─▶ vik-worker (arq, same image)
```

On the free plan the proxy reaches `vik-api` by its public URL (free web services can't receive private-network traffic); on a paid plan, by its private hostport.

### 2.1 Services

| Service | Type | Image | Responsibilities |
|---|---|---|---|
| `vik-web` | Render web | `frontend/Dockerfile` (node:22-alpine, standalone) | UI; `/api/v1/*` proxy reading `API_INTERNAL_URL` at runtime (multipart + streaming); `/api/realtime` (serves `API_PUBLIC_WS_URL` to the browser); `/api/health` (health check) |
| `vik-api` | Render web | `backend/Dockerfile` (python:3.13-slim + uv, tesseract) | REST, uploads, one multiplexed WebSocket per tab (`/ws?token=…`); latency-critical work (dashboard chat, CSV/XLSX parsing, claim checks, chair step, live interrupts, VC lines); migrations at startup under `pg_advisory_lock`; jobs inline on the free tier |
| `vik-worker` | Render worker | same image, `arq vik.jobs.WorkerSettings` | Jobs: FR-7 document facts (`extract`), knowledge-base import, organize and index (`kb_ingest`, `kb_organize`, `kb_index`), report rebuilds (`report`). Commented out in the free phase |
| Postgres | Render Postgres 17 | — | Only durable store; created outside the Blueprint (`DATABASE_URL` entered on the first sync) |
| Key Value | Render Key Value | — | arq queue, pub/sub, pitch hot state, caches, rate limit, spend counter; created outside the Blueprint (`REDIS_URL` in `render.yaml`) |

### 2.2 Backend package layout (`backend/vik/`)

```
vik/
  api.py                FastAPI app, routers, lifespan (migrations, pool, Redis, realtime hub, stale-job sweeper)
  config.py             pydantic-settings (env)
  auth.py               access-code gate, cookie signing, rate limit, budget guard
  db.py  migrate.py     asyncpg pool; SQL migrations in backend/migrations/
  kv.py                 Redis/Valkey: queue, pub/sub, caches, counters; the daily spend (mirrored in Postgres)
  jobs.py               arq WorkerSettings + job runner (inline when JOBS_MODE=inline)
  realtime.py           WebSocket hub, Redis pub/sub bridge
  audit.py              deterministic audit: numbers ±2%, [src:id] benchmarks, [kb:path] note quotes, valuation blocklist → citations[]
  qa.py                 Ask Vik: deterministic answer; Gemini phrasing held to the same audit
  report.py             session report (code): verdict, questions, ledger, knowledge gaps, action plan, sources
  playbooks.py          read_playbook(topic) over data/playbooks/*.md and geo/{CA,US,UK,generic}.md; question banks
  model/
    canonical.py        canonical field vocabulary (units, granularity)
    loader.py           CSV/XLSX parse → column profiles; sign/currency normalization; wide→long transpose
    mapping.py          heuristic mapping proposal → ColumnMapping[]; confirm/apply
    financials.py       confirmed datasets + mappings → one canonical, period-indexed model
    context.py          TruthContext: everything code knows about the confirmed source of truth
    figures.py          Figure / MissingFigure / Fact
    metrics.py          availability-aware metric definitions → Figure
    truth.py            attack list over 12 lenses; check_claim; forecast-vs-history gaps; deck claims
    coverage.py         coverage checklist
    sources.py          cite_source over data/sources.yaml (filtered by business_model/stage); glossary
    currencies.py fx.py reporting currencies; Bank of Canada conversion
  services/
    engagements.py      engagement lifecycle: profile → uploads → datasets + mappings → facts → confirm
    dashboards.py       stored widget specs + layout (values evaluated by code on every read); chat
    jobs_handlers.py    report, extract (FR-7), kb_ingest, kb_index, kb_organize
    fx.py               Bank of Canada daily rates, cached in Redis
  viz/
    spec.py  dsl.py     WidgetSpec; series DSL parser → AST (no eval)
    evaluate.py         series evaluation with per-point provenance
    echarts.py          ECharts option builder (dataset.source filled by code only)
    defaults.py         default dashboard on confirm
    phrases.py          offline phrase → widget spec or time range
  llm/
    client.py           google-genai wrapper: route → model tier + thinking level, structured output, tool loop, stop/refusal checks, error mapping, per-model pacing and 429 rests, usage → spend
    schemas.py          Pydantic outputs (Memo, BeliefUpdate, ChairDecision, LineReview, JudgeScore, DocFact, …)
    minds.py            investor and Vik minds, LLM path (same contracts as court/minds.py)
    mapper.py           column mapper, LLM path
    docs.py             FR-7 document facts: one structured call per part, then code verification (pypdf)
  kb/                   knowledge base (docs/07, docs/08): ingest, convert, ocr, store, organize, autofill, truthnote,
                        chunk, bm25, voyage, index, rag, ask, tools (kb_search / kb_read), routes
  areopagus/
    schema.py           VCPersona
    kits/               QuantAudit, Customer, Channel, Governance, RedTeam, Market, Terms, Milestone, Benchmark, Cash, Product
    builtin/            <investor>.yaml (5)
    templates.yaml      builder templates (4)
    builder.py          description → VCPersona draft (Gemini, or a keyword heuristic)
    registry.py         built-ins and templates from the repo, custom from Postgres
  court/
    session.py          the after-pitch Q&A: start → (answer → score → beliefs → referee → chair → speak)* → end → report
    referee.py          pure-code candidate ranking, cooldowns, fairness, depth cap, jump-in margin
    minds.py            investor and Vik minds, deterministic path (offline, and on any LLM failure)
    review.py           Vik's review of a drafted line (code checks)
    knowledge.py        knowledge checks (deterministic path)
  pitch/
    session.py          deck, transcript segments, ledger, interrupt policy, after-mode Q&A
    verify.py           the pitch's statements against the knowledge base
    voice.py            ElevenLabs STT token issuing, TTS streaming per voice_id
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
2. The heuristic mapper (`model/mapping.py`) proposes `ColumnMapping[]{source_column, canonical_field, unit, confidence, note}`; with a key, Gemini 3.8 Flash (route `mapper`, medium thinking, ≤ 30 s) refines it for series tables, merged with the heuristic (targets validated, units set by code).
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

`data/playbooks/geo/{CA,US,UK,generic}.md` selected by `company_profile.country`. Canada: SR&ED, CCPC status; US: R&D credit, SBIR; UK: R&D relief. Everything marked "verify with an advisor". Plato's kit (Governance) reads these.

## 4. Citation pipeline

1. **Figures** carry formula, inputs and source refs (CSV row range or pack-fact page). `check_claim` returns the Figure it compared against.
2. **PDF/DOCX/MD facts (FR-7, `extract` job, `llm/docs.py`):** one structured call per part (route `doc_facts`, `MODEL_DEEP`: Gemini 3.8 Flash, or Gemini 4 Argon on a paid key; medium thinking, 32,000 max output tokens) returns `DocFact[]{name, label, value, unit, currency, period, kind, page, cited_text}`, where `cited_text` is the passage copied word for word. A PDF goes in as the file itself: inline up to 15 MB, otherwise through the Gemini Files API (deleted after the call). DOCX, markdown and tables without a date axis go in as text. Long documents are read in parts (15 PDF pages, or about 60,000 text characters), up to four at once; a part whose answer overflows or fails validation is halved and read again, down to one page or a short chunk. Code then decides what lands: it locates each quote itself (the model's page first, then every page via pypdf; the char span in text), so the page is code's; a quote it can't find is kept but flagged `verified: false` with a note for the confirm table; a fact whose number isn't in its quote, or that is labelled a deck, slide or pitch claim, is dropped.
3. **Benchmarks** only via `cite_source`; the audit requires `[src:id]` on any benchmark phrase.
4. **Agent output → footnotes:** the audit maps each number to its Figure and each `[src:id]` to its source, attaching `citations[]` to the message. Frontend renders superscripts with a hover card (formula, inputs, source) and an "open source" action. Reports end with a Sources section.
5. **Dashboards:** every plotted point keeps `{value, formula, inputs, source}` for click-to-explain.

## 5. Agents

### 5.1 SDK usage rules (`llm/client.py`)

- One async wrapper over the `google-genai` SDK: every call is `client.aio.models.generate_content`. `LLM.parse()` for structured outputs, `LLM.text()` for free text, `LLM.run_tools()` for tool loops, `LLM.upload()` for a PDF too big to send inline.
- Each route (`ROUTES`) names a model tier (`vik`, `investor`, `deep`, `fast`, `tiny`), an effort and `max_tokens`; the effort is Gemini's `thinking_level` (`low` / `medium` / `high`). Thinking can't be turned off on these models and counts against `max_output_tokens`, so every route leaves room for it.
- Structured outputs: `response_mime_type: application/json` plus `response_json_schema`, the Pydantic model's JSON schema with every `$ref` inlined; the reply is validated with the same model, and a reply that doesn't validate is an `LLMError`.
- Tool loops run in our code, over plain function declarations (the SDK's automatic function calling is disabled). The model's turn goes back exactly as returned, so its thought signatures are preserved; a tool that fails or doesn't exist returns an `{"error": …}` object the model can read. The loop ends in the structured answer; one still calling tools after its last iteration (6 by default) is an `LLMError`.
- Why the model stopped is checked before any content is read: a `prompt_feedback.block_reason`, or a finish reason of `SAFETY`, `PROHIBITED_CONTENT`, `BLOCKLIST`, `SPII`, `RECITATION`, `IMAGE_SAFETY` or `LANGUAGE` → `LLMRefusal`; `MAX_TOKENS` or any other non-`STOP` reason → `LLMError`.
- Errors: HTTP 400 → `LLMError` ("bad request"), except Gemini's answer to an invalid key (400 "API key not valid") → `LLMUnavailable` ("credentials rejected"), which shows in `GET /kb/status` → `llm_health`; 401/403 (credentials), 429 (rate limit), other API errors, connection errors and timeouts → `LLMUnavailable`. Callers treat every `LLMError` the same way: the deterministic path answers.
- Routes on a request path carry `timeout_s`: one bound on the whole call (or the whole tool loop), with no SDK retries inside it. Other routes use the SDK's retries (3 attempts, on 408 and 5xx only). The SDK never retries a 429: on a free key a retry spends the quota again.
- Pacing and 429s (`Pacer`, per process): on the free tier each model gets at most `GEMINI_RPM` requests a minute (default 10; 0 = no pacing). A request waits for a slot, bounded by its route's timeout where it has one, so a court turn falls back to the offline mind rather than wait long. On any tier, when the API answers 429 that model rests for the error's `RetryInfo.retryDelay` (else `GEMINI_COOLDOWN_S`, default 60 s): calls to it raise `LLMUnavailable` ("rate limited") at once, without a request, so the offline path answers immediately; other models are unaffected. Google applies free-tier quotas per project and per model; the daily quota resets at midnight Pacific.
- No explicit prompt-cache breakpoints: Gemini caches repeated prompt prefixes implicitly, and system parts are ordered stable → volatile (rules, then persona or figures). Cached tokens are billed at the cached rate.
- Every call is stateless: rebuilt from Postgres; transcripts append-only. Within a tool loop the model's own turns are sent back as returned; nothing is replayed across calls.
- Spend on the free tier (`GEMINI_TIER=free`, the default): calls are priced at $0, nothing is reserved, `over_budget()` is always false and no route returns 402; the limits are requests, kept by the pacer.
- Spend on a paid key (`GEMINI_TIER=paid`): each response's `usage_metadata` is priced at list rates (prompt and tool-use prompt tokens at the input rate, cached tokens at the cached rate, candidate and thinking tokens at the output rate) and added to `vik:spend:{date}` and the Postgres `spend` table. Before every call, including each call of a tool loop, an estimate (the prompt plus a full `max_tokens` reply) is reserved on the same counter and settled after, so parallel calls see each other. Over budget → `BudgetExceeded`, and LLM routes return 402 with a clear message; when neither store can be read, live calls fail closed.
- Prices (USD per 1M tokens, input / output incl. thinking / cached input; applied on a paid key only), at the 2027 list rates so the budget never under-counts: `gemini-4-argon` 4.00 / 20.00 / 0.20; `gemini-3.8-flash` 1.50 / 7.50 / 0.15; `gemini-3.6-flash` 1.50 / 7.50 / 0.15; `gemini-3.5-flash-lite` 0.30 / 2.50 / 0.03. An unlisted model is priced at the dearest rate (4.00 / 20.00 / 0.40).
- Not used: the SDK's automatic function calling (our loop owns tool calls, budget and timeouts) and explicit context caches.

### 5.2 Roster

The court's agents: Vik orchestrates on Gemini 3.8 Flash (`MODEL_VIK`) and the five investors run on Gemini 3.6 Flash (`MODEL_INVESTOR`), all at a low thinking level (`VIK_ROUTES` / `INVESTOR_ROUTES` in `llm/client.py`). The investors research before the meeting (memo tool loop over figures, kit tools and the founder's notes) and question the founder's claims, foresight, business judgment and knowledge of their own notes. Other routes use the tiers `MODEL_DEEP` (Gemini 3.8 Flash), `MODEL_FAST` (Gemini 3.8 Flash) and `MODEL_TINY` (Gemini 3.5 Flash-Lite). The table names these free-tier defaults; on a paid key, `MODEL_VIK` and `MODEL_DEEP` can be set to Gemini 4 Argon.

| Agent (route) | Model / thinking | Shape | Output |
|---|---|---|---|
| VC memo (`memo`) | Gemini 3.6 Flash, low | tool loop over read-only tools (§5.3), ending in parse; ≤ 60 s for the whole loop | `Memo{thesis, hypotheses[{attack_id, claim, lens, evidence[figure_id], severity, confidence}], mind_changers[], opening_question}` |
| VC update + bid (`update_bid`) | Gemini 3.6 Flash, low | one parse per VC per answer, all parallel; ≤ 12 s | `BeliefUpdate{deltas[{hyp_id, new_confidence, why}], bid, intent: follow_up|new_topic|jump_in|pass, target_hyp}` |
| VC speak (`speak`) | Gemini 3.6 Flash, low | text; ≤ 12 s | question text in persona style |
| Vik chair (`chair`) | Gemini 3.8 Flash, low | parse ≤ `CHAIR_TIMEOUT_S` (6 s) | `ChairDecision{action: call_on|interject|end_session, vc_id?, intent (incl. `knowledge`), hypothesis_id?, note?}` |
| Vik line review (`review`) | Gemini 3.8 Flash, low | parse; ≤ 12 s; code's checks always count | `LineReview{verdict: approve|revise, issues[], note}`; one rewrite by the VC when sent back |
| Vik scoring (`judge`) | Gemini 3.8 Flash, low | parse, independent of VCs; ≤ 20 s | scores dims 2–5, rationale, good/missing, strong-answer rewrite; on a knowledge check, uses Vik's verdict |
| Knowledge probes (`probes`, Vik) | Gemini 3.8 Flash, low | parse, at session start, over retrieved note passages; ≤ 30 s | `ProbeList{probes[{vc_id, passage_id, question, answer_quote}]}`; the quote must be verbatim |
| Knowledge question / verification (`ask_knowledge` / `verify`) | Gemini 3.6 Flash low / Gemini 3.8 Flash low | text / parse; ≤ 12 s each | the VC's wording; `KnowledgeVerdict{verdict, explanation}` audited against the notes |
| Claim extractor (`claims`) | Gemini 3.5 Flash-Lite, low | parse; ≤ 12 s | `Claim[]{text, metric, value, unit, period, is_forecast}` |
| Column mapper (`mapper`) | Gemini 3.8 Flash, medium | parse; ≤ 30 s | `ColumnMapping[]` |
| Doc fact extractor (`doc_facts`) | Gemini 3.8 Flash, medium | one parse per part (§4) | `DocFact[]` |
| Ask Vik (`qa`) | Gemini 3.8 Flash, medium | text, or a tool loop over `kb_search` / `kb_read` when the vault has notes and no index exists; ≤ 25 s | reply held to the citation audit |
| Ask Vik from passages (`qa_rag`) / catch-all (`qa_full`) | Gemini 3.5 Flash-Lite, low / medium | parse ([08-RAG](08-RAG.md)) | `RagReply{answerable, reply}` |
| Organizer (`kb_organize`, `kb_hubs`) / profile autofill (`kb_profile`) | Gemini 3.8 Flash, medium | parse | note plans, hub notes / profile draft with quotes |
| Persona generator (`persona`) | Gemini 3.8 Flash, medium | parse | `PersonaDraft` → `VCPersona` |
| Pitch statements (`pitch_assertions`) / pitch vs notes (`pitch_kb`) | Gemini 3.5 Flash-Lite low / Gemini 3.8 Flash low | parse; ≤ 12 s / ≤ 20 s | verbatim statements / a verdict per statement with a verbatim passage quote |

Session reports are written by code (`report.py`), with no LLM call.

### 5.3 Tools (all read-only)

Declared to the model as functions with a JSON schema for their arguments. The memo loop gets `get_metric(id)`, the persona's kit tools (deterministic analyses per kit, returning Figures) and, when the vault has notes, `kb_search(query)` / `kb_read(note)`. Ask Vik's tool loop (before an index exists) gets `kb_search` / `kb_read`. Every other agent gets what it needs in the prompt (figures, fact sheet, retrieved passages).

### 5.4 The Areopagus

- `schema.py` `VCPersona{id, name, archetype, bio, cheque_role, priorities{lens: weight} over 12 lenses, style{tone, interrupt_tendency, follow_up_depth, aggression}, signature_move, question_seeds[], dealbreakers[], scoring_weights, voice_id, base_archetype?, kits[], builtin}`.
- `kits/` deterministic analyses returning Figures: QuantAudit, Customer, Channel, Governance, RedTeam, Market, Terms (dilution/waterfall math only, never valuation), Milestone, Benchmark, Cash (default-alive, fatal-pinch date), Product.
- Minds: `court/minds.py` (deterministic) and `llm/minds.py` (Gemini, same contracts) build memos, update beliefs and bid, and speak for every persona. **No-concession rule** in `update_and_bid`: confidence on a hypothesis can only drop when the answer cites a Figure matching it.
- Built-ins (`areopagus/builtin/*.yaml`), named for Greek philosophers: Aristotle (Lead Seed Fund, lines-not-dots), Thales (Angel Operator, stories-before-numbers), Xenophon (Strategic Investor, trap terms), Plato (Government-Backed Fund, mandate audit) and Socrates (Skeptical Partner, pre-mortem chain). The replaced archetypes (Series A readiness, capital efficiency, term sheets, technical diligence, market) keep only their question banks, as strong-answer anchors. Builder templates (`areopagus/templates.yaml`): Impact Partner, Family Office Principal, Accelerator Partner, Revenue-Based Lender. Default panel all five (`registry.DEFAULT_PANEL`); max 5 seated.
- Custom investors run on the same minds, driven by their spec (lenses, style, question seeds, kits); `base_archetype` records the built-in a fork came from.
- Guardrails: persona text inside a delimited block treated as character description; field caps; audit on every VC.

### 5.5 Court turn loop

The court is the Simulation's after-pitch Q&A: `POST /pitch/{id}/end` in after mode opens it (session mode `simulate`), and the browser runs it by voice on `/court/{id}/*`. There is no stand-alone text court.

1. Session start: memos in parallel (one call per VC, inside the request); gap ownership assigns attack-list items by lens weight (severity ≥ 0.8 may be shared); the pitch's notes discrepancies are seated as doubts.
2. Founder answer stored → parallel: claim extraction + `check_claim` (accuracy score) beside retrieval; then Vik's score (after her knowledge verification when the question was a knowledge check) and every VC `update_and_bid`.
3. Referee (pure code): candidates ranked by `bid × lane_fit × fairness_decay(turns_since_spoke)`; follow-up bonus when the answer was weak; depth cap 3; jump-in margin 0.2; cooldowns. When a knowledge check is due (`court/knowledge.py`: from the second question, then every third, never after a weak answer, at most cap ÷ 3), Vik puts it at the top of the list. Knowledge checks are a setting of the court engine; the Simulation opens the court with them off.
4. Chair step: Vik (`MODEL_VIK`, low) over bids, open hypotheses, ledger, goals, budgets and the candidate list → `ChairDecision`; referee validates; invalid or later than `CHAIR_TIMEOUT_S` (6 s) → top code candidate. Every decision logged.
5. Speak: the VC drafts the line → deterministic audit (failure → regenerate once → offline line) → **Vik reviews it** (`court/review.py` + `LineReview`): sent back → one rewrite, kept if it passes code's checks → stored with the review in `turns.audit.review` → TTS.
6. Coaching: Coached mode time-out after two weak answers on one hypothesis (names the gap, points at the Figure, adds no figure).
7. End conditions: question cap (the Simulation sets 6; the engine allows 4–20, default 8), no candidate left to ask (hypotheses resolved, < 0.2 or > 0.8), founder ends. Then the report, built by code and audited.

### 5.6 Simulation pipeline

Setup: `POST /pitch/deck` reads the deck (PDF pages rendered as images, PowerPoint slides as text); each slide's figures are checked by `check_claim` (they become the TruthPack's deck claims, so the attack list sees them) and its statements against the knowledge base (`pitch_assertions`, then `pitch_kb`). Presenting: STT final segments tagged with slide → claims (Flash-Lite `claims`, merged with code's extraction) → `check_claim` → ledger → UI, plus the same notes check. Live mode: candidate = `severity × interrupt_tendency × lane_fit` in code; 30 s cooldown; ≤ 1 per slide; the interrupting line is written by code from the check; founder answers by voice; judged; resume. After mode: spoken claims join the deck claims → chaired Q&A (6 questions, up to four notes discrepancies as doubts). Delivery stats from the transcript (words, fillers).

### 5.7 Audit (`audit.py`)

Regex-extract every number; normalize units ($, K, M, %, months, x); each must match a Figure within ±2% or be a quoted founder statement (or sit inside a verbatim note quote followed by its `[kb:path]`); `[src:id]` required on benchmark phrases; valuation/investment-advice blocklist; emits `citations[]`. Applies to every VC, Vik, coaching card and report.

## 6. Live dashboards

- `viz/spec.py` `WidgetSpec{template: line|area|bar|stacked_bar|combo_bar_line|waterfall|kpi|gauge_ring|heatmap|scatter|table, title, series[{ref: metric id | DSL expr}], window, group_by, compare, presentation{stack, smooth, dual_axis, labels, mark_lines, sort, unit}}`.
- DSL: `+ − × ÷`, `sum avg rolling cmgr pct_of yoy mom cumsum lag`, parsed to an AST; unknown functions/columns/attribute access rejected; no `eval`.
- `evaluate.py` computes series with per-point provenance; cached in Redis by spec hash; invalidated when a dataset or fact changes.
- `echarts.py` builds the full option (`dataset.source`, `dataZoom` inside + slider, shared `axisPointer`, `brush`, theme names). The LLM never supplies values.
- Realtime: `dashboards.version` optimistic concurrency; diffs on `vik:dashboard:{id}`; all tabs apply via WebSocket (the store dedupes by version).
- Frontend: `components/charts/EChart.tsx` (~40-line wrapper over `echarts/core`), `lib/echarts-theme.ts` (`vik-dark` / `vik-light` from CSS tokens), widgets `WidgetFrame`, `EChartWidget`, `KpiWidget`, `MissingDataTile`, `DashboardGrid` (react-grid-layout; CSS-grid fallback), `DashboardChat` (PromptBar → `POST /dashboards/{id}/chat`; diffs arrive over the WebSocket). `recharts` removed after `TrendChart` migrates.

## 7. Realtime protocols

| Channel | Transport | Payload |
|---|---|---|
| `/ws?token=…&channels=dashboard:{id},session:{id}` | WebSocket, one per tab, ping 20 s; token from `GET /realtime/token` | `{type, channel, session_id, version, ts, payload}`: `vc.turn.done`, `chair.decision`, `score.ready`, `knowledge.checked`, `coach.timeout`, `session.ended` (session); `widget.diff`, `layout.diff`, `time_range.diff` (dashboard); `job.status` (session, engagement or `kb`); `kb.index.ready`, `kb.index.failed` (`kb`) |
| Redis pub/sub | `vik:{channel}` (`vik:session:{id}`, `vik:dashboard:{id}`, …) | same envelope; API fan-out to sockets |

Reconnect: clients drop envelopes at or below the last `version` seen per channel and re-fetch REST state; Postgres is the record (turns, widgets), so a redeploy mid-session loses nothing.

## 8. API surface (REST, under `/api/v1`, cookie-gated except `/healthz` and `/auth/*`)

Full contract: [API.md](API.md).

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/access` | Exchange access code for cookie |
| GET | `/healthz` | `{db, kv}`; 503 when `db` is `error` (`kv` is informational) |
| GET/POST/PUT | `/engagements`, `/engagements/{id}`, `/engagements/{id}/profile` | List; create; company profile |
| POST | `/uploads` | Multipart ≤ 10 MB → `uploads` row (and the knowledge base); triggers parse or the FR-7 `extract` job |
| GET/PUT | `/datasets/{id}/mapping` | Proposed mapping; confirm/edit |
| POST/DELETE | `/engagements/{id}/facts`, `/engagements/{id}/facts/{fact_id}`, `/engagements/{id}/confirm` | Founder facts; confirm → attack list, coverage, default dashboard, search index |
| GET/POST | `/truth`, `/metrics`, `/metrics/{id}`, `/attack-list`, `/coverage`, `/claims/check` | Figures and claim checks |
| GET/POST/PATCH/DELETE | `/dashboards/{id}`, `/dashboards/{id}/widgets`, `/dashboards/{id}/layout`, `/dashboards/{id}/time-range` | Dashboard + widgets; layout and time range persistence |
| POST | `/dashboards/{id}/widgets/preview`, `/dashboards/{id}/chat`, `/dashboards/{id}/chat/catch-all` | Evaluate a spec without saving; Ask Vik; the catch-all offer's answer |
| GET/POST/PUT/DELETE | `/areopagus`, `/areopagus/{id}`, `/areopagus/{id}/fork` | Personas (custom writable; built-ins read-only) |
| POST | `/areopagus/generate` | NL → persona preview |
| POST | `/pitch/start` (409 without confirmed TruthPack), `/pitch/deck`, `/pitch/{id}/segment`, `/pitch/{id}/reply`, `/pitch/{id}/end` | Simulation; after mode's end opens the court |
| GET/POST | `/court/{id}`, `/court/{id}/answer`, `/court/{id}/end`, `/sessions` | The after-pitch Q&A |
| POST | `/voice/stt-token` | Short-lived ElevenLabs token |
| GET | `/voice/tts?text=&speaker=&voice_id=` | Streamed audio |
| GET | `/sessions/{id}/report`, `/reports`, `/reports/{id}`, `/reports/{id}.md` | Reports |
| GET/POST/PUT/DELETE | `/kb/*` | Knowledge base ([07](07-KNOWLEDGE-BASE.md), [08](08-RAG.md)) |
| GET/POST | `/jobs/{id}`, `/jobs/{id}/retry` | Job status (404 unknown); retry re-queues a `failed`/`stale` job (409 in any other state) |

## 9. Security, limits and cost

- Access gate: `ACCESS_CODE` → signed cookie (`COOKIE_SECRET`, generated by Render) carrying an HMAC of `ACCESS_CODE`, so changing the code revokes every issued cookie; every route but `/healthz` and `/auth/*` requires it; 401 otherwise. The cookie is host-only on the web origin (same-origin proxy; no `Domain`).
- `/healthz` is 503 when Postgres is unreachable (Redis state is informational), so Render's health check restarts a broken instance.
- Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are off when `COOKIE_SECURE=true`.
- Rate limit per IP (`vik:rl:{ip}`; client IP from `X-Forwarded-For` only behind `TRUSTED_PROXY_CIDRS`); wrong access codes also capped across all IPs (`ACCESS_FAILURES_PER_MIN`); daily USD budget guard on LLM routes (paid key only; a free key is paced per model instead).
- Secrets only via env (`GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `VOYAGE_API_KEY`, `ACCESS_CODE`, `COOKIE_SECRET`, `DATABASE_URL`); never `ARG` in Dockerfiles; `.env` gitignored, `.env.example` committed. A public deploy (`COOKIE_SECURE=true`) refuses to start on the development `ACCESS_CODE` or `COOKIE_SECRET`.
- Data sent to Gemini: on the LLM path the founder's financials and notes go to Gemini. On the free tier Google may use what is sent to improve its products (Gemini API pricing page, free tier: "Used to improve our products: Yes"). For real company data use a paid key (`GEMINI_TIER=paid`), or `LLM_MODE=offline`.
- Uploads ≤ 10 MB, bytea in Postgres (Render has no free disk). Request bodies over `REQUEST_MAX_BYTES` are 413 before they are read.
- ElevenLabs key never reaches the browser; STT uses short-lived tokens.
- Persona spec text is data, never instructions.

## 10. Docker, Render and CI

- `backend/Dockerfile`: multi-stage on `python:3.13-slim`; uv from `ghcr.io/astral-sh/uv:0.11.33`; `uv sync --frozen --no-dev` before copying source; tesseract for OCR; non-root; `PYTHONUNBUFFERED=1`; `entrypoint.sh` serves `uvicorn vik.api:app` on `$PORT` with `--ws-ping-interval 20 --no-proxy-headers`, or runs its arguments (worker, migrations).
- `frontend/Dockerfile`: `node:22-alpine` multi-stage; `npm ci` → `next build` (standalone) → runtime copies `public`, `.next/standalone`, `.next/static`; `HOSTNAME=0.0.0.0`; no hardcoded PORT; `CMD ["node","server.js"]`.
- `docker-compose.yml`: `db` (`pgvector/pgvector:pg17`), `kv` (valkey:8), `api` (reload, `JOBS_MODE=inline`), profile `full`: `worker`, `web` (`next dev`). `docker compose up db kv` or `docker compose --profile full up`.
- `render.yaml` (no `rootDir`; repo-root-relative paths): `vik-api` web/docker, free plan, with `healthCheckPath: /healthz`, `autoDeployTrigger: checksPass`, `buildFilter` on `backend/**` and `render.yaml` (tests and evals ignored), its own secrets (`DATABASE_URL`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `VOYAGE_API_KEY`, `ACCESS_CODE`, all `sync: false`) and `REDIS_URL` set to the existing Key Value's internal URL; `maxShutdownDelaySeconds` is not allowed on the free plan (add 60 when paid); `vik-worker` (commented out on free); env group `vik-shared` (`COOKIE_SECRET`, `WEB_ORIGIN`, `GEMINI_TIER=free`, `LLM_MODE`, `DAILY_USD_BUDGET`) shared by api and worker; `vik-web` with `healthCheckPath: /api/health`, `API_INTERNAL_URL` set to the API's public URL on the free plan (the `vik-api` hostport on a paid plan) and `API_PUBLIC_WS_URL` set after first deploy. The Postgres and the Key Value exist already and are not declared, so a sync never creates second copies.
- Fallback: if `runtime: docker` is refused on the free web plan, move `vik-api` to `0.5c-512mb` immediately.
- CI (`.github/workflows/ci.yml`): backend (uv sync, ruff, pytest with Postgres (pgvector) + Valkey service containers), frontend (npm ci, tsc, eslint, build), e2e (Playwright against the API with offline agents and the production web build), docker-build (both images, no push, smoke-tests the API image). Render auto-deploys `main` on green.
- Demo switch (day before judging): api and web → `0.5c-512mb`, uncomment worker, `JOBS_MODE=worker`, `preDeployCommand: python -m vik.migrate` on `vik-api`, raise `DAILY_USD_BUDGET` if the key is paid (`GEMINI_TIER=paid`); in the dashboard, the database → `basic-256mb` and the Key Value → `starter`. Downgrade after.

## 11. Environment variables

| Var | Service | Notes |
|---|---|---|
| `DATABASE_URL` | api, worker | `sync: false`: the existing database's Internal Database URL, entered on the first Blueprint sync |
| `REDIS_URL` | api, worker | the existing Key Value's internal URL, set in `render.yaml` |
| `JOBS_MODE` | api | `inline` (free) / `worker` |
| `WEB_ORIGIN` | api, worker | CORS allow-origin only (no cookie `Domain` is set); env group `vik-shared` |
| `DAILY_USD_BUDGET`, `LLM_MODE` | api, worker | budget default 5 (20 in `vik-shared`), applied only with `GEMINI_TIER=paid`; `LLM_MODE` `auto` (default) or `live` use Gemini when a key is set, `offline` never; env group `vik-shared` |
| `COOKIE_SECRET` | api, worker | `generateValue: true` in env group `vik-shared` |
| `COOKIE_SECURE` | api | `true` on Render, `false` on http://localhost; `true` also disables `/docs`, `/redoc`, `/openapi.json` |
| `GEMINI_API_KEY` | api, worker | `sync: false`; Google AI Studio key (`GOOGLE_API_KEY` is read too). Unset = the offline agents |
| `GEMINI_TIER` | api, worker | `free` (default; also set in `vik-shared`) or `paid`. `free`: calls are priced at $0, no reservation, no 402, and each model is paced to `GEMINI_RPM`; Google may use what is sent to improve its products. `paid`: list prices against `DAILY_USD_BUDGET`, with reservations and the 402 |
| `GEMINI_RPM` | api, worker | default 10: requests a minute per model on the free tier, per process; 0 = no pacing |
| `GEMINI_COOLDOWN_S` | api, worker | default 60: how long a model rests after a 429 when the error carries no `retryDelay` (any tier) |
| `ELEVENLABS_API_KEY` | api, worker | `sync: false` |
| `MODEL_DEEP`, `MODEL_FAST`, `MODEL_TINY`, `MODEL_VIK`, `MODEL_INVESTOR` | api, worker | defaults `gemini-3.8-flash`, `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.8-flash`, `gemini-3.6-flash`: all free-tier models, three of them so each has its own quota. On a paid key, `MODEL_DEEP` / `MODEL_VIK` can be `gemini-4-argon` (not on the free tier) |
| `CHAIR_TIMEOUT_S` | api | default 6.0: Vik's pick of the next speaker, then `ranked[0]` |
| `VIK_VOICE_ID`, `ELEVENLABS_TTS_MODEL` | api | Vik's ElevenLabs voice (unset = a premade voice); TTS model (default `eleven_flash_v2_5`) |
| `ACCESS_CODE` | api | `sync: false` |
| `TRUSTED_PROXY_CIDRS` | api | default `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128,fc00::/7`; `X-Forwarded-For` is honoured only when the direct peer is in these ranges, and the client is the rightmost entry outside them (Render's edge proxy and private network are inside) |
| `ACCESS_FAILURES_PER_MIN` | api | default 60: wrong access codes per minute across all IPs before `/auth/access` returns 429 for everyone |
| `REQUEST_MAX_BYTES` | api | default unset = `KB_UPLOAD_MAX_BYTES` + 4 MiB (54 MiB); larger bodies get 413 before they are read |
| `VOYAGE_API_KEY` | api, worker | `sync: false`; knowledge-base embeddings and reranking ([08-RAG](08-RAG.md)); unset = BM25 only |
| `EMBED_MODEL`, `RERANK_MODEL`, `RERANK_MODEL_FAST`, `RAG_CONF_MIN`, `RAG_FULL_MAX_TOKENS`, `RAG_REUSE_EMBEDDINGS` | api, worker | defaults in `vik/config.py` |
| `API_INTERNAL_URL`, `API_PUBLIC_WS_URL` | web | read at request time, never baked at build |

## 12. Testing and evals

- Unit/integration (`backend/tests/`): metrics on three fixtures; mapping accuracy; `check_claim`; audit cases; migration idempotency; pub/sub round trip; inline vs worker parity; DSL evaluator parity with `lib/tidewell.ts` values and rejection of unsafe expressions; ECharts builder contains no LLM-supplied values; persona validation; kit figures match the engine; referee and chair fallbacks; gate and auth codes; grep test for "Tidewell".
- LLM path (`test_llm.py`, `test_llm_api.py` and others): a real `google.genai.Client` over an `httpx.MockTransport` with recorded Gemini responses (`tests/llm_fakes.py`), so request building (model, thinking level, schema), response parsing, refusals, error mapping, tool loops and spend are exercised with no network.
- Evals (`backend/evals/`): the retrieval eval (`evals/rag/run.py`, recall@5 and MRR on the fixture vault; [08-RAG](08-RAG.md)). Not built yet: a self-play harness with scripted founders (strong, average, evasive, wrong numbers) measuring grounding, distinctness, no-concession, belief direction, chair quality and latency.
- Frontend: tsc, eslint, build; Playwright E2E in CI.
- Manual on Render after each deploy.

## 13. Technical risks

| Risk | Mitigation |
|---|---|
| `runtime: docker` refused on free plan | `0.5c-512mb` at once |
| Free API cold start (~1 min) during judging | Paid tier the day before; landing pings `/healthz` on load |
| Free Postgres expires (2026-11-17) | Upgrade in the dashboard before then; upgrading keeps data |
| Free Key Value loses queued jobs; redeploy or sleep cuts a running job | Sweeper marks old `queued`/`running` rows `stale`, a cancelled run ends `failed` (`interrupted`); both show Retry; nothing durable in Redis |
| The model misquotes a document or names the wrong page | Code locates every quote itself (pypdf per page, char span in text) and the page is code's; an unfound quote is flagged `verified: false`; a fact whose number isn't in its quote is dropped |
| Memos slow or costly | Parallel calls on Gemini 3.6 Flash at a low thinking level; 60 s bound on the whole tool loop; budget guard on a paid key; the offline memo on any failure |
| Thinking can't be turned off and counts against `max_output_tokens` | Every route's `max_tokens` leaves room for it; `MAX_TOKENS` → `LLMError` → the offline path; an FR-7 part that overflows is halved and read again |
| Gemini unavailable, rate-limited or the key rejected | `LLMUnavailable` → the deterministic path for that step (an invalid key's 400 "API key not valid" too, as "credentials rejected"); `GET /kb/status` → `llm_health` shows the last live call's outcome |
| Free-tier quota runs out (per project and per model; the daily quota resets at midnight Pacific) | Defaults spread over three models, each with its own quota; the pacer keeps each model under `GEMINI_RPM`; after a 429 the model rests and its calls go offline at once, without a request; a paid key (`GEMINI_TIER=paid`) for heavier use |
| react-grid-layout on React 19 | Verify; fallback CSS-grid reorder |
| Tool loops rejected when thought signatures are lost | The model's turn is sent back exactly as returned; every call is otherwise stateless, rebuilt from Postgres; append-only transcripts |
