# Vik — App Flow

Version 1.0 — 17 Oct 2026. Companion to [01-PRD](01-PRD.md), [03-UI-UX](03-UI-UX-DESIGN.md) and [05-Backend schema](05-BACKEND-SCHEMA.md). Each flow lists the screen, what the user does, what the system does (code vs agent), and what is persisted.

---

## 0. Map

```
Access gate ──▶ Landing ──▶ Knowledge base ──▶ Fill dashboard ──▶ TruthPack flow ──▶ Dashboard
                            (files, notes)                       (profile → mapping → facts → confirm)

Dashboard ⇄ Vik chat (widgets)        Simulation (deck + voice) ──▶ Q&A after (court) ──▶ Report
Areopagus (cards, builder) ⇄ Simulation roster    Reports (engagements, sessions)
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

### 2a. Knowledge base → Fill dashboard → Confirm knowledge base

The knowledge base is the only way in. No chat or wizard step takes a file: the dashboard chat has no attach button and
the mapping step has no "add another file". Any file posted to `POST /uploads` by another client is also imported into
the knowledge base. To change what the agents know, the founder adds files to the knowledge base, presses **Fill
dashboard**, checks the autofilled draft and presses **Confirm knowledge base**, which updates search for every agent.

| Step | User | System | Persisted |
|---|---|---|---|
| 1 | Drops any files into the knowledge base | `POST /kb/import`: each file converted to notes (any type: Office, OpenDocument, PDF with OCR, email with attachments, images, recordings transcribed; a stub note for the rest), organized and linked | `kb_files`, `kb_notes` |
| 2 | Presses **Fill dashboard** | `POST /kb/autofill`: the profile proposed from the vault (Gemini, each value with a verified quote; code heuristics for the rest, including country and city), every table and document sent through the intake (column mapper, FR-7 facts). No search rebuild here | `engagements` (draft), `company_profiles`, `uploads`, `datasets` |
| 3 | Step 01 **Profile**: checks the autofilled fields (each shows its source) | — | `company_profiles` |
| 4 | Step 02 **Mapping**: reviews the proposed mapping, fixes low-confidence rows, keeps extras as raw columns or names a **custom field** ("+ New custom field…"); one **Save and continue** saves every table | The loader already found the header under any title rows, the date axis (any date format, Year + Month columns, Excel serials), scaled "$000" values, rolled daily rows and ledgers up to the period and transposed wide layouts; Gemini 3.8 Flash proposes `ColumnMapping[]`; choosing another date column re-reads the table | `dataset_mappings`, `datasets` |
| 5 | Step 03 **Facts**: reviews extracted facts (documents) and typed facts; edits/removes rows; unverifiable citations flagged | One structured Gemini pass per document (long ones in parts; a part whose answer overflows is halved): each fact with its quoted passage and page. Code locates the quote (pypdf for PDFs) and keeps the page where it finds it, flags a quote it can't find, drops a fact whose number isn't in its quote; facts merged with dataset-derived fields | `truthpacks.facts` (pending) |
| 6 | Step 04 **Confirm**: reads the coverage checklist, presses **Confirm knowledge base** | Unreviewed low-confidence column guesses are kept as raw columns (noted on the table) rather than blocking. Code computes all metrics (`Figure` / `MissingFigure`), the attack list over 12 lenses, the coverage checklist and the **default dashboard**. If a TruthPack was already confirmed for a different company, this **starts a new engagement**; the previous stays under Reports | `truthpacks.confirmed_at`, `dashboards`, `widgets`, `engagements.status` |
| 6b | — | The confirmed reading is written to `company/Confirmed knowledge base.md` (profile and sources, how each column is read, kept facts; no figures) and the search index is rebuilt from the whole vault in the background ([08-RAG.md](08-RAG.md)) | `kb_notes`, `kb_index_builds`, `kb_chunks` |
| 7 | Redirected to `/dashboard` | Status pill shows `{Company} · confirmed` | — |

### 2b. Sample companies

The app never preloads or offers a sample company. The knowledge base is the single source of truth: to try a sample, import its files from `backend/data/samples/<id>/` into the knowledge base and press **Fill dashboard**, then check and confirm the draft at `/knowledge/confirm` like any other. Tests load the fixtures directly (`tests/helpers.py`).

### 2c. Typed figures

The founder types "our MRR is $80K and burn is $40K" in any Vik chat → claim extractor (Gemini 3.5 Flash-Lite) → pending facts with source `founder_stated` → shown in the Facts step (or a "3 facts to confirm" chip in the status pill). After confirmation they are Figures of kind `founder_claim`; VCs treat them as claims, not records.

### 2d. Typed question

The landing has no prompt bar: its one button, **Get started**, opens the knowledge base. Questions go to Vik in the dashboard chat (§3), which answers from the data and the notes and may add a widget ([08-RAG.md](08-RAG.md)).

## 3. Dashboard

| Step | User | System | Persisted |
|---|---|---|---|
| 1 | Opens `/dashboard` | Loads `dashboards` + `widgets` for the active engagement; opens the WebSocket (`/ws?session=dashboard:{id}`) | — |
| 2 | Reads KPIs, hovers/clicks points | Explain popover from per-point provenance | — |
| 3 | Asks Vik "burn excluding SR&ED as % of revenue by quarter" | AG-UI run on `/agui/dashboard`: Vik calls `list_metrics` → `preview_series(spec)` → `add_widget(spec)`; `evaluate.py` computes the series (code); `echarts.py` builds the option; version bumps; diff published on `vik:dashboard:{id}`; the chat tab gets a "Widget added" card with Undo; other tabs receive the diff over WebSocket | `widgets`, `dashboards.version`, `dashboard_messages` |
| 4 | "Zoom to the last 6 months" | Frontend tool `set_time_range` → every chart's dataZoom moves; range chip appears | — |
| 5 | Drags, resizes, pins, removes | `PATCH /dashboards/{id}/layout` (optimistic concurrency on `version`) | `dashboards.layout` |
| 6 | Asks for churn cohorts without a cohort table | Vik replies with the missing-data reason and adds nothing | `dashboard_messages` |
| 7 | Uploads another file / edits a fact | Recompute affected Figures; widgets re-evaluated; diffs pushed | `datasets`, `widgets` |
| 8 | "Ask about this" on a widget | `useCopilotReadable` adds the widget spec and series summary to Vik's context | — |

Conflict: two tabs edit layout at once → the second `PATCH` gets 409 with the newer version; the client re-applies.

## 4. The court (Q&A after a pitch)

The court has no page of its own: it is the Simulation's Q&A in Questions-after mode (§5), opened by `POST /pitch/{id}/end` and spoken by voice.

| Step | User | System | Persisted |
|---|---|---|---|
| 1 | Presses **End** after presenting in Questions-after mode | `/pitch/{id}/end` opens the court: a `sessions` row (mode `simulate`, 6 questions, coached, knowledge checks off) on the seated panel; a memo for each VC (in parallel, inside the request); up to four pitch-vs-notes discrepancies added as doubts (round robin, claims-lens investors first); agenda from the memos | `sessions`, `memos` |
| 2 | Listens to the opening | Vik introduces the Q&A; the referee ranks the opening bids, Vik picks, and that VC's first question is drafted (audited), reviewed by Vik and spoken | `turns`, `chair_decisions` |
| 3 | Answers out loud (typed when there is no mic) | `POST /court/{id}/answer` stores the turn; in parallel: claims (Gemini 3.5 Flash-Lite) + `check_claim` → accuracy; Vik scores dims 2–5; every VC `update_and_bid` (no-concession rule) | `turns`, `claims`, `scores`, `beliefs` |
| 4 | — | Referee ranks candidates (bid × lane_fit × fairness; follow-up bonus; depth cap 3; jump-in margin 0.2; cooldowns) → **Chair step** (`MODEL_VIK`, Gemini 3.8 Flash by default, low thinking, within `chair_timeout_s`, 6 s) → validated decision or code fallback → chosen VC drafts the line → Vik reviews it (one rewrite if sent back) → it plays in the VC's voice | `chair_decisions`, `turns` |
| 5 | Sees the score land in the Scoring panel | `score.ready` published (coached) | — |
| 6 | Gives a second weak answer on the same hypothesis | Vik interjects with a time-out naming the gap and pointing to the Figure, no new numbers; the next question moves to another topic | `turns` (kind `coach`) |
| 7 | Presses **End Q&A** (or the cap is reached, or no investor has anything left to ask) | `POST /court/{id}/end`: Vik's debrief; the report is built in code (`vik.report`) and audited before it is stored | `reports` |
| 8 | Opens the report | `/reports/{id}` | — |

`GET /court/{id}` returns the session view (turns, scores, claims, who speaks next) for the browser. Knowledge checks ([05 §2.24](05-BACKEND-SCHEMA.md)) are part of the engine but off here: the Q&A's note questions are the discrepancies.

Budget exceeded mid-session (paid key, `GEMINI_TIER=paid`) → banner; the session pauses at the next turn and can resume tomorrow (state is in Postgres). The default free key has no budget: when a model is rate limited (429) it rests, and the steps that use it run on the offline minds until it is back.

## 5. Simulation (pitch)

| Step | User | System | Persisted |
|---|---|---|---|
| 0 | Opens `/simulation` without a confirmed TruthPack | Setup state shows the gate message; `POST /pitch/start` would return 409 | — |
| 1 | Uploads a PDF deck, picks the panel, sets Interrupt live / Questions after | `POST /uploads` → deck pre-scan job (slide text via pypdf + page images + TruthPack summary → `SlideFinding[]`); ledger seeded; memos run with deck findings | `uploads`, `sessions.deck`, `claims`, `memos` |
| 2 | Presses the mic | `POST /voice/stt-token` → browser opens ElevenLabs realtime STT with the short-lived token; timer starts; current slide tracked | — |
| 3 | Speaks through the slides (prev/next) | Each final transcript segment → `POST /pitch/{id}/segment` (slide, t_offset) → claims (Gemini 3.5 Flash-Lite) → `check_claim` → ledger update pushed over WebSocket; hot state in `vik:pitch:{id}` | `turns` (founder segments), `claims` |
| 4a | **Live mode**: says "growing 10% a month" | Ledger `contradicts` → interrupt candidate scored in code (`severity × interrupt_tendency × lane_fit`) → Vik approves/vetoes ≤ 1 s (code decides on timeout) → cooldown (30 s) and per-slide cap (1) checked → capture pauses → VC speaks ≤ 2 sentences via TTS in its voice → founder answers by voice → Vik scores → resume | `turns`, `scores`, `chair_decisions` |
| 4b | **After mode**: finishes the deck | Transcript + ledger → the court (§4), 6 questions | same as court |
| 5 | Stops | Delivery stats computed from transcript timing (talk time per slide, fillers, dodges); report job | `reports` |
| 6 | Opens the report | Slide-by-slide notes and claims ledger sections populated | — |

Fallback: if STT fails, the founder types lines into the prompt bar; the same pipeline runs.

**Built today.** The pitch room has no chat: one button (Start, then End), the stage, captions and the panel's voices.
Deck pre-scan runs in the request (no worker yet); delivery stats are words, fillers and seconds per slide.

| Step | User | System | Persisted |
|---|---|---|---|
| 0 | Opens `/simulation` | `POST /pitch/start` (no body): 409 → the source-of-truth notice; 200 → `{voice}` | — |
| 1 | Drops a PDF or PowerPoint (optional), seats the panel, picks Interrupt live / Questions after | `POST /pitch/deck` → a PDF's pages rendered (JPEG, returned only), a PowerPoint's slides read as title and lines → figures → `check_claim`; statements → retrieval over the knowledge base → supported / contradicted / new / unclear with a verbatim note quote → slide chips and two ledgers. The deck is never added to the knowledge base | `truthpacks.deck_claims`, `vik:deck:{id}` |
| 2 | Presses **Start** | Mic opens (paused); `POST /pitch/start {mode, panel, deck_id}` → Vik's opening plays; then the mic streams to realtime Scribe | `vik:pitch:{id}` |
| 3 | Presents, moving through slides (←/→) | A pause of ~0.9 s commits a segment → `POST /pitch/{id}/segment` (slide, t_ms) → figures checked against the data and statements against the notes → ledgers ("Claims ledger", "Against your notes") and a toast | `vik:pitch:{id}` |
| 4a | **Live**: says something that contradicts the data or their own notes | The segment comes back with `interrupt` (code: severity × interrupt tendency × lane fit; ≤ 1 per slide; 30 s cooldown). Mic pauses, the investor's line (written by code from the check) plays in their voice; the mic reopens; a ~1.8 s pause ends the answer → `POST /pitch/{id}/reply` → judged; the investor hands back; presenting resumes | same |
| 4b | **After**: presents without interruptions | Segments are checked, nothing interrupts | same |
| 5 | Presses **End** | Live: `POST /pitch/{id}/end` → Vik's wrap-up (counts from the ledger). After: Vik's "compare notes" line plays while `/pitch/{id}/end` stores the spoken claims beside the deck's and opens a court session (§4: `simulate`, 6 questions, coached, knowledge checks off) whose doubts include up to four discrepancies between the pitch and the notes (contradicted first, then claims the notes don't cover), each asked as "Your pitch says …, but your own notes say …: which is right, and what changed?" | `sessions`, `turns`, `memos` |
| 6 | **After**: answers each question out loud | Each question plays in the asker's voice; the mic reopens; a pause ends the answer → `POST /court/{sid}/answer`; the button reads **End Q&A**, which calls `/court/{sid}/end` | as the court (§4) |
| 7 | Opens the report | The court's report (after mode) at `/reports/{id}`; live mode writes none | `reports` |

Without an ElevenLabs key, lines show as captions for their reading time and the founder types into a one-line field
under the button; with the key but the mic blocked (or no mic streaming in the browser), the panel still speaks and the
founder types. The flow is the same. Voices are configured, not listed (a restricted key may lack `voices_read`):
built-ins and builder templates carry a premade `voice_id` in their YAML cast for the archetype (`ARCHETYPE_VOICES` in
`pitch/voice.py`), and Vik uses `VIK_VOICE_ID` or a premade one. `POST /pitch/start` casts the sitting once
(`pitch.voices`, speaker → voice): each seat keeps its own voice, else takes its archetype's next free one, else a
library voice fixed by its id, so nobody in the room (Vik included) shares a voice. Live interrupts, hand-backs and
the Q&A all play with that cast.

## 6. Areopagus

### 6a. Browse
`/areopagus` → `GET /areopagus` returns built-ins (from the repo) and custom personas (from Postgres), both schema-validated. Cards show lens, signature move, kits, voice preview (`GET /voice/tts` with a fixed line).

### 6b. Build from a description
1. "+ New investor" → sheet → describe → `POST /areopagus/generate` (Gemini 3.8 Flash, structured output) → `VCPersona` preview.
2. Edit form (lens sliders pick kits; style sliders; chips; signature move; voice picker).
3. "How would they open?" → `POST /areopagus/{draft}/test` runs a memo on the current TruthPack and returns the opening question (audited).
4. Save → `POST /areopagus` → `vc_personas` row, visible to every browser in the workspace; appears in rosters immediately.

From the Simulation: the roster's "+" opens `/areopagus?build=1&return=simulation&panel=…` (the seated ids). Save returns to `/simulation?panel=…&added=…` with the new investor seated beside the panel (when a seat is free); closing the builder returns to `/simulation?panel=…` unchanged. While a pitch runs the seats are locked and "+" only opens the builder.

### 6c. Fork, edit, duplicate, delete, import/export
Fork a built-in → copy with `base_archetype` set (keeps the archetype's coded hooks). Edit/duplicate/delete only custom (`PUT`/`DELETE /areopagus/{id}`). Import YAML/JSON validates against the schema and shows errors inline; export writes YAML.

Guardrails on save: field caps, delimited persona block, audit applied to the test question.

## 7. Reports

1. `/reports` → `GET /reports` grouped by engagement (current first). Readiness trend from `reports` (overall per report, `delta_vs_previous`).
2. `/reports/{id}` → `GET /reports/{id}` renders the sections that have content; "Download Markdown" → `/reports/{id}.md`.
3. "Pitch again" → `/simulation`. The action plan's items carry a `lens` chip; nothing launches from them.
4. Past engagements are read-only; "Reopen" is not offered (one engagement at a time).

## 8. Across sessions

- Nothing is carried from one session into the next. Founder memory (weakness ledger, drill marks, `recall(topic)`) was removed with Preparation; migration `0011_retire_founder_memory.sql` dropped its table. A new Q&A starts from the TruthPack, the founder's notes and that pitch.
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
| Daily budget reached (paid key only) | LLM routes return 402; UI banner; dashboards and reports stay readable |
| Gemini rate limit (429) | That model rests for the error's `retryDelay` (else `GEMINI_COOLDOWN_S`, 60 s); its calls take the offline path at once, other models carry on; on the free tier each model is also paced to `GEMINI_RPM` requests a minute |
| Gemini key rejected | 400 "API key not valid" → "credentials rejected"; every step runs offline; `GET /kb/status` → `llm_health` shows it |

## 10. Demo path (judging, ~5 minutes)

1. Enter the access code. Knowledge base → import the **Harbor Labs** CSVs (renamed as unfamiliar files) → **Fill dashboard** → check the profile → mapping screen → confirm → dashboard with footnoted figures.
2. Import the Tidewell files and fill again → second engagement; the first appears under Reports.
3. Two tabs: ask Vik for "burn excluding SR&ED as % of revenue by quarter" → widget in both; click a bar → formula + source rows; "zoom to the last 6 months".
4. Simulation Live: 3-slide deck, say "growing 10% a month" → interruption in a VC voice; ledger `contradicts`.
5. Simulation Questions after, with the five philosophers seated → End → the panel confers → Vik chairs (reviews each line) → a gap between the pitch and the notes is asked about → a weak growth answer gets a follow-up and a coached time-out → End Q&A → report with Sources.
6. Ask "what valuation should we raise at?" → declined with an explanation.
