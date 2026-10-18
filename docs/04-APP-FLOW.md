# Vicky — App Flow

Version 1.0 — 17 Oct 2026. Companion to [01-PRD](01-PRD.md), [03-UI-UX](03-UI-UX-DESIGN.md) and [05-Backend schema](05-BACKEND-SCHEMA.md). Each flow lists the screen, what the user does, what the system does (code vs agent), and what is persisted.

---

## 0. Map

```
Access gate ──▶ Landing ──┬─▶ Upload / sample / typed figures ──▶ TruthPack flow ──▶ Dashboard
                          │                                     (profile → mapping → facts → confirm)
                          └─▶ typed question ──▶ Haiku intent ──┬─▶ Dashboard (data/dashboard)
                                                                └─▶ Preparation (practice)

Dashboard ⇄ Vicky chat (widgets)        Preparation (court) ──▶ Report
Simulation (deck + voice) ──▶ Report    Areopagus (cards, builder)    Reports (engagements, sessions, drills)
```

Every tab shares one **engagement** (company) at a time. All screens except `/healthz` require the access cookie.

## 1. Access

| Step | User | System | Persisted |
|---|---|---|---|
| 1 | Opens any URL | No cookie → redirect to `/access` | — |
| 2 | Enters the access code | `POST /api/v1/auth/access` compares against `ACCESS_CODE`; sets signed HTTP-only cookie (30 days); rate-limits attempts per IP | — |
| 3 | Redirected to the original URL | Landing pings `/healthz` to warm the API | — |

Failure: wrong code → inline error; 5 failures in a minute → 429 for 60 s.

## 2. Landing → first source of truth

### 2a. Upload a file

| Step | User | System | Persisted |
|---|---|---|---|
| 1 | Attaches CSV/XLSX/PDF/DOCX/MD in the prompt bar | `POST /uploads` (≤ 10 MB) stores bytes; CSV/XLSX parsed inline into `datasets` with column profiles; PDF/DOCX enqueue an extraction job | `uploads`, `datasets`, `jobs` |
| 2 | Lands in the TruthPack flow, step 01 | If no engagement is active or the upload clearly belongs to a new company (name mismatch), Vicky asks for the **company profile**; values inferred from the file are prefilled as "inferred" | `engagements` (draft), `company_profiles` |
| 3 | Confirms the profile | — | `company_profiles` |
| 4 | Step 02 **Mapping** (CSV/XLSX only): reviews the proposed mapping, fixes low-confidence rows, keeps extras as raw columns; one **Save and continue** saves every table | The loader already found the header under any title rows, the date axis (any date format, Year + Month columns, Excel serials), scaled "$000" values, rolled daily rows and ledgers up to the period and transposed wide layouts; Sonnet proposes `ColumnMapping[]`; choosing another date column re-reads the table | `dataset_mappings`, `datasets` |
| 5 | Step 03 **Facts**: reviews extracted facts (documents) and typed facts; edits/removes rows; unverifiable citations flagged | Two-pass citation extraction job; pypdf verification; facts merged with dataset-derived fields | `truthpacks.facts` (pending) |
| 6 | Step 04 **Confirm**: reads the coverage checklist, confirms | Code computes all metrics (`Figure` / `MissingFigure`), the attack list over 12 lenses, the coverage checklist and the **default dashboard**. If a TruthPack was already confirmed for a different company, this **starts a new engagement**; the previous stays under Reports | `truthpacks.confirmed_at`, `dashboards`, `widgets`, `engagements.status` |
| 7 | Redirected to `/dashboard` | Status pill shows `{Company} · confirmed` | — |

### 2b. Sample companies

The app never preloads or offers a sample company. The knowledge base is the single source of truth: to try a sample, import its files from `backend/data/samples/<id>/` into the knowledge base and press **Fill dashboard**, then check and confirm the draft at `/knowledge/confirm` like any other. Tests load the fixtures directly (`tests/helpers.py`).

### 2c. Typed figures

The founder types "our MRR is $80K and burn is $40K" in any Vicky chat → Haiku claim extractor → pending facts with source `founder_stated` → shown in the Facts step (or a "3 facts to confirm" chip in the status pill). After confirmation they are Figures of kind `founder_claim`; VCs treat them as claims, not records.

### 2d. Typed question

Landing prompt bar → `POST /intent` (Haiku): `data` / `dashboard` → `/dashboard?q=…` (Vicky answers there and may add a widget); `practice` → `/preparation?q=…` (the question seeds the court's agenda). With no confirmed TruthPack, Vicky answers generally and offers a sample or upload.

## 3. Dashboard

| Step | User | System | Persisted |
|---|---|---|---|
| 1 | Opens `/dashboard` | Loads `dashboards` + `widgets` for the active engagement; opens the WebSocket (`/ws?session=dashboard:{id}`) | — |
| 2 | Reads KPIs, hovers/clicks points | Explain popover from per-point provenance | — |
| 3 | Asks Vicky "burn excluding SR&ED as % of revenue by quarter" | AG-UI run on `/agui/dashboard`: Vicky calls `list_metrics` → `preview_series(spec)` → `add_widget(spec)`; `evaluate.py` computes the series (code); `echarts.py` builds the option; version bumps; diff published on `vicky:dashboard:{id}`; the chat tab gets a "Widget added" card with Undo; other tabs receive the diff over WebSocket | `widgets`, `dashboards.version`, `dashboard_messages` |
| 4 | "Zoom to the last 6 months" | Frontend tool `set_time_range` → every chart's dataZoom moves; range chip appears | — |
| 5 | Drags, resizes, pins, removes | `PATCH /dashboards/{id}/layout` (optimistic concurrency on `version`) | `dashboards.layout` |
| 6 | Asks for churn cohorts without a cohort table | Vicky replies with the missing-data reason and adds nothing | `dashboard_messages` |
| 7 | Uploads another file / edits a fact | Recompute affected Figures; widgets re-evaluated; diffs pushed | `datasets`, `widgets` |
| 8 | "Ask about this" on a widget | `useCopilotReadable` adds the widget spec and series summary to Vicky's context | — |

Conflict: two tabs edit layout at once → the second `PATCH` gets 409 with the newer version; the client re-applies.

## 4. Preparation (court)

| Step | User | System | Persisted |
|---|---|---|---|
| 1 | Opens `/preparation`; seats VCs (default all five: Aristotle, Thales, Xenophon, Plato, Socrates; max 5); sets question cap, coaching mode and knowledge checks; optionally adds a custom VC via "+" | Roster from `GET /areopagus`; Chair card fixed | — |
| 2 | Sends the first answer or presses Start | `POST /court/start` → `sessions` row; gap ownership computed; **memo jobs** for each VC (parallel; inline on free tier); memo progress snippets streamed | `sessions`, `memos`, `jobs` |
| 3 | Watches the opening | Vicky (chair) sets the agenda from the attack list + founder goals, introduces the panel, calls the first VC with an intent; the VC's opening question streams (audited sentence by sentence) | `turns`, `chair_decisions` |
| 4 | Answers (typed or mic) | `POST /court/{id}/answer` stores the turn; in parallel: Haiku claims + `check_claim` → accuracy; Judge scores dims 2–5; every VC `update_and_bid` (no-concession rule) | `turns`, `claims`, `scores`, `beliefs` |
| 5 | — | Referee ranks candidates (bid × lane_fit × fairness; follow-up bonus; depth cap 3; jump-in margin 0.2; cooldowns) → **Chair step** (Sonnet low, ≤ 1.5 s) → validated decision or code fallback → chosen VC speaks | `chair_decisions`, `turns` |
| 6 | Sees a score card appear under the answer (Coached) or only the temperature glyph move (Realistic) | Score cards gated by coaching mode | — |
| 7 | Gives a second weak answer on the same hypothesis (Coached) | Vicky interjects with a time-out card naming the gap and pointing to the Figure, no new numbers; next question resumes | `turns` (kind `coach`) |
| 8 | Marks questions Repeat / Study in the right column, presses "Drill N selected" | `POST /court/{id}/drills` saves the marks (kind `drill`); a live session ends (its report keeps the weak spots); `POST /court/start` with `drills[]` opens a session on the same panel whose first questions are the drilled topics (repeat before study; Vicky puts each at the top of the ranked list until asked, never ahead of a weak-answer follow-up). The right column shows which came back | `founder_memory` |
| 9 | Ends the session (or cap/time/resolution reached) | Vicky debriefs; report job runs (Report writer → LLM audit → deterministic audit); "Report ready" card | `reports`, `founder_memory` (weakness ledger, answers, rewrites) |
| 10 | Opens the report | `/report/{id}` | — |

Budget exceeded mid-session → banner; the session pauses at the next turn and can resume tomorrow (state is in Postgres).

## 5. Simulation (pitch)

| Step | User | System | Persisted |
|---|---|---|---|
| 0 | Opens `/simulation` without a confirmed TruthPack | Setup state shows the gate message; `POST /pitch/start` would return 409 | — |
| 1 | Uploads a PDF deck, picks the panel, sets Interrupt live / Questions after | `POST /uploads` → deck pre-scan job (slide text via pypdf + page images + TruthPack summary → `SlideFinding[]`); ledger seeded; memos run with deck findings | `uploads`, `sessions.deck`, `claims`, `memos` |
| 2 | Presses the mic | `POST /voice/stt-token` → browser opens ElevenLabs realtime STT with the short-lived token; timer starts; current slide tracked | — |
| 3 | Speaks through the slides (prev/next) | Each final transcript segment → `POST /pitch/{id}/segment` (slide, t_offset) → Haiku claims → `check_claim` → ledger update pushed over WebSocket; hot state in `vicky:pitch:{id}` | `turns` (founder segments), `claims` |
| 4a | **Live mode**: says "growing 10% a month" | Ledger `contradicts` → interrupt candidate scored in code (`severity × interrupt_tendency × lane_fit`) → Vicky approves/vetoes ≤ 1 s (code decides on timeout) → cooldown (30 s) and per-slide cap (1) checked → capture pauses → VC speaks ≤ 2 sentences via TTS in its voice → founder answers by voice → Judge → resume | `turns`, `scores`, `chair_decisions` |
| 4b | **After mode**: finishes the deck | Transcript + ledger → chaired Q&A loop (6–8 questions) identical to the court loop | same as court |
| 5 | Stops | Delivery stats computed from transcript timing (talk time per slide, fillers, dodges); report job | `reports` |
| 6 | Opens the report | Slide-by-slide notes and claims ledger sections populated | — |

Fallback: if STT fails, the founder types lines into the prompt bar; the same pipeline runs.

## 6. Areopagus

### 6a. Browse
`/areopagus` → `GET /areopagus` returns built-ins (from the repo) and custom personas (from Postgres), both schema-validated. Cards show lens, signature move, kits, voice preview (`GET /voice/tts` with a fixed line).

### 6b. Build from a description
1. "+ New investor" → sheet → describe → `POST /areopagus/generate` (Sonnet structured output) → `VCPersona` preview.
2. Edit form (lens sliders pick kits; style sliders; chips; signature move; voice picker).
3. "How would they open?" → `POST /areopagus/{draft}/test` runs a memo on the current TruthPack and returns the opening question (audited).
4. Save → `POST /areopagus` → `vc_personas` row, visible to every browser in the workspace; appears in rosters immediately.

### 6c. Fork, edit, duplicate, delete, import/export
Fork a built-in → copy with `base_archetype` set (keeps the archetype's coded hooks). Edit/duplicate/delete only custom (`PUT`/`DELETE /areopagus/{id}`). Import YAML/JSON validates against the schema and shows errors inline; export writes YAML.

Guardrails on save: field caps, delimited persona block, audit applied to the test question.

## 7. Reports

1. `/reports` → `GET /reports` grouped by engagement (current first). Readiness trend from `founder_memory` and `reports`.
2. `/report/{id}` → `GET /sessions/{id}/report` renders the 10 sections; "Export Markdown" → `/reports/{id}.md`.
3. "Drill this" / "Start drill session" → `POST /court/start` with `drills[]` → a Prepare session whose agenda starts with those topics.
4. Past engagements are read-only; "Reopen" is not offered (one engagement at a time).

## 8. Founder memory across sessions

- After every session the report job writes: weakness ledger by lens (severity, last seen), answers + scores, rewrites seen, drills done.
- At session start (`vicky.memory`): pending drills (or the `drills[]` given) are matched to the new memos by attack item (else by doubt) and seated with the best-lens investor if nobody owns them; they gain severity and lead `sessions.agenda`. The weak spots of the last 3 reports raise their doubt's severity and keep its confidence (never lowered: no-concession rule). Used drills are marked `used_by` the new session.
- During sessions VCs and Vicky call `recall(topic)` ("Last session you said 10%"); Aristotle's `on_answer` compares with earlier answers across sessions.
- Readiness orb score = latest report's overall; the trend compares to the previous session of the same engagement.

## 9. Realtime and recovery

| Event | Behaviour |
|---|---|
| New tab opened | Connects `/ws?session=…`; receives current version; subscribes to dashboard and session channels |
| Widget/turn in another tab | Diff over pub/sub → WebSocket → store applies if `version` is newer (dedupes AG-UI + WS) |
| Redeploy mid-session | Socket drops; client reconnects with `since_version`; server replays from Postgres; ember reconnect line disappears |
| Job lost (free Key Value restart) | `jobs` row stays `queued` past its TTL → UI shows Retry → re-enqueue |
| Audit blocks a sentence | Stream for that turn is dropped; regenerated once with feedback; final fallback to the memo's opening question |
| Chair late or invalid | Code pick used; decision logged with `fallback: true` |
| Daily budget reached | LLM routes return 402; UI banner; dashboards and reports stay readable |

## 10. Demo path (judging, ~5 minutes)

1. Enter the access code. Knowledge base → import the **Harbor Labs** CSVs (renamed as unfamiliar files) → **Fill dashboard** → check the profile → mapping screen → confirm → dashboard with footnoted figures.
2. Import the Tidewell files and fill again → second engagement; the first appears under Reports.
3. Two tabs: ask Vicky for "burn excluding SR&ED as % of revenue by quarter" → widget in both; click a bar → formula + source rows; "zoom to the last 6 months".
4. Preparation with the five philosophers → memos stream → Vicky chairs (reviews each line) → a knowledge check is verified against a cited note → a weak growth answer gets a follow-up and a Coached time-out → end → report with Sources.
5. Simulation Live: 3-slide deck, say "growing 10% a month" → interruption in a VC voice; ledger `contradicts`. After mode → Q&A + report.
6. Ask "what valuation should we raise at?" → declined with an explanation.
