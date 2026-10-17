# Vicky: AI VC pitch coach for June Analytics (Catalyst Team 18)

## Context
June Analytics' brief (`docs/challenge/Catalyst - Team 18 Challenge Brief.md` plus the supporting PDF) asks for **Vicky**, an AI venture capitalist. Vicky prepares the founders of fictional Tidewell Systems for a $4M seed raise by analyzing the numbers, preparing the founder and simulating the pitch. Judges score usefulness, financial accuracy, investor realism, interactivity and responsible AI, and want deep agentic behavior rather than one-shot chat.

The user's product concept has two modes:
- **Prepare**: load the company data. The app builds dashboards automatically, then a **court of AI VC agents** grills the founder from different investor perspectives.
- **Pitch Simulation**: the founder presents an uploaded PDF deck out loud. The VCs read the slides plus the live transcript and grill the founder against the **source of truth** (the financials). A toggle chooses between **live interruptions** and **questions after the presentation**. Voice runs on **ElevenLabs**: speech-to-text (STT) for the founder, a text-to-speech (TTS) voice per VC.
- **A source-of-truth document must be submitted before the Simulation can start.** VCs use it to ask home-hitting questions.
- Both modes end in a **score plus an extensive feedback report**.

Constraints: solo, about 1 day; FastAPI + Next.js; Claude for reasoning. Rules from Appendix G:
- Numbers come from code, not the LLM.
- Every figure carries a source tag.
- A separate audit check reviews output.
- Missing data is reported as missing.
- No valuation or investment advice.

## Data reality
Only CSV 01 (`backend/data/samples/tidewell/income_statement_monthly.csv`) is on disk. CSVs 02–10, the xlsx and Appendix J are missing.
- Add `backend/data/pack_facts.yaml` with figures transcribed from PDF Appendices A–C. Each fact carries `appendix:` and `kind: historical|forecast|founder_claim`.
- The loader prefers real CSVs when present, so the missing files can be dropped in later.
- Churn, NRR and cohort figures without CSVs 05/06 are labeled "per data pack summary".

## Layout (under `june/`; see `06-IMPLEMENTATION-PLAN.md` §1 for the current tree)
```
backend/data/ CSVs, pack_facts.yaml, areopagus/custom/*.yaml, questions.yaml (App. D), sources.yaml (App. F), glossary.yaml (App. I)
backend/vicky/
  figures.py       Figure: value, unit, formula, inputs, kind, source
  loader.py        parse "$1,234.00"/"-$5.00" CSVs → pandas; merge pack_facts
  metrics.py       deterministic metrics → Figure      (the source of truth)
  truth.py         claims checker + forecast-vs-history gaps; check_claim(text_claim) → verdict
  dashboard.py     chart-ready series + KPI tiles from metrics
  areopagus/       schema.py (VCPersona), mind.py (memo, belief state, gap ownership), registry.py (load/validate builtin+custom), generate.py (NL → spec), builtin/*.yaml
  llm/             client.py (SDK wrapper: effort, structured output, fallbacks, refusal handling), schemas.py, prompts/
  agents/          memo.py, belief.py, speak.py, extractor.py, deck_reader.py, judge.py, reporter.py, auditor_llm.py, persona_gen.py
  tools.py         read-only @beta_tool functions over metrics/truth
  referee.py       bid → speaker selection, gap ownership, cooldowns (pure code)
  db.py, schema.sql  Neon Postgres
  court.py         Prepare session loop
  pitch.py         session state, transcript segments, claim extraction, interrupt policy, post-pitch Q&A
  truthpack.py     source-of-truth ingest (CSV/XLSX/PDF/DOCX/MD) → confirmed facts + attack list
  scoring.py       rubric + deterministic accuracy score
  report.py        report agent → extensive feedback JSON/Markdown
  audit.py         number check + no-valuation check on every VC/coach message
  voice.py         ElevenLabs: STT token issuing + TTS per persona voice
  api.py           FastAPI routes + WebSocket for pitch
backend/tests/
frontend/    Next.js (App Router, Tailwind, Recharts, pdf.js)
```

## Shared core (build first)

**Metrics engine.** Deterministic code with no LLM. Targets from Appendix H and the glossary:
- ARR $1.29M (Sep subscription revenue × 12)
- Compound monthly growth: about 9% over 12 months, about 5% Jul→Sep
- Gross margin 92% as booked, 74% including customer success
- Fully loaded CAC about $3,200; payback about 9–10 months
- Burn about $58K a month excluding SR&ED; runway about 8 months
- Burn multiple 0.6 (0.8 without SR&ED)
- Northern Comfort about 10% of MRR
- Churn 2.0% / 1.6%; NRR about 88%; GRR about 81%
- Forecast runway about 22 months on the plan versus about 17 on historical drivers

**Truth layer.**
- Checks the 9 deck claims (Fix / Reword / Show as upside / Remove).
- Lists forecast assumption gaps, e.g. rep ramp 1 vs 3 months, churn 1% vs 2%, the price rise, Northern Comfort at 600 seats unsigned.
- Exposes `check_claim(metric, value)` for spoken claims.

**Areopagus (the VC registry).** Areopagus is the curated set of prebuilt VC personas shipped with the app.

The prebuilt five come from Appendix E. Each looks for a different kind of gap:

| VC | Focus |
|---|---|
| Lead Seed Fund | Metrics depth: ARR method, retention, burn multiple, forecast vs history |
| Angel Operator | Customers, the sales motion, whether founders know their numbers without looking |
| Strategic | Channel fit, data ownership, exclusivity and rights |
| Government-backed Fund | Governance, finance function, SR&ED handling, Canadian IP |
| Skeptical Partner | The one claim that breaks the story |

**Thinking, analytic and distinct.** Each built-in VC reasons for itself instead of reading from a question list. Each one follows the same loop, implemented in `areopagus/mind.py`:
1. **Private analysis pass** before the first question. The VC uses Claude extended thinking and the metrics tools to study the TruthPack through its own lens. It writes a hidden **investment memo** with:
   - Its thesis
   - 3–5 **weakness hypotheses**, each with evidence (Figure refs) and a confidence score
   - What would change its mind
2. **Belief state** that updates every turn. After each founder answer, the VC re-scores its hypotheses. A strong, cited answer lowers its concern; a dodge or a wrong number raises it. The next question goes after the hypothesis with the highest remaining uncertainty × severity. Follow-ups come from what the founder just said, not from a script.
3. **Gap ownership**. When several VCs sit together, the orchestrator splits the attack-list categories by each VC's lens. That way they don't repeat each other, and each one finds gaps the others don't. Overlap happens only when a gap is severe enough that more than one investor would really raise it.
4. **The notepad is shown after the session.** The report includes each VC's memo, how their beliefs moved, and what would have changed their verdict.

Each built-in VC has its own method and a signature move:

| VC | Analytic method | Signature move | Gaps it owns |
|---|---|---|---|
| **Lead Seed Fund** | Quant auditor: recomputes every headline metric its own way (ARR without one-time fees, cohort NRR/GRR, burn multiple, CAC payback on a margin that includes support) | Follows a number down three levels: "Which months? Which customers?" | Metric definitions, retention, unit economics, runway to Series A |
| **Angel Operator** | Pattern-matches from evidence to the number: asks for the customer story, then the figure behind it | "Tell me about the last customer who churned" | Sales motion and rep ramp, early churn, how well the founders know their numbers |
| **Strategic** | Maps the value chain: where Tidewell sits beside their channel, who owns the data, what lock-in looks like | Floats a rights ask such as a right of first refusal (ROFR), to see if the founder notices the trade-off | Channel concentration, partner referrals, data ownership, exclusivity |
| **Government-backed Fund** | Diligence checklist: controls, reporting, governance, use of non-dilutive money | "Who prepares your financial statements?" | No finance function, SR&ED accounting, board and governance, Canadian IP |
| **Skeptical Partner** | Red-team pre-mortem: assumes the deal failed and works back to the cause | Interrupts, asks "So what?", stress-tests one claim until it breaks | Growth slowing from 9% to 5%, Northern Comfort concentration, forecast built on hope, competitive moat |

A custom VC gets the same thinking loop automatically. Its spec only supplies the lens, style and priorities.

**Persona schema.** Defined as a pydantic `VCPersona` in `backend/vicky/areopagus/schema.py`:
- `id`, `name`, `archetype`, `bio`
- `cheque_size`
- `priorities[]` (weighted), `gap_lenses[]`: which attack-list categories it hunts (claims, forecast, retention, unit economics, concentration, runway, governance, market, team)
- `style`: tone, interrupt tendency (0–1), follow-up depth
- `question_seeds[]`, `dealbreakers[]`
- `scoring_weights` over the 5 rubric dimensions
- `voice_id`
- `builtin: bool`

**Storage.**
- Builtins: `backend/vicky/areopagus/builtin/*.yaml`, read-only in the UI.
- Custom: `backend/data/areopagus/custom/*.yaml`.
- The registry loads both and validates each file against the schema.

**Selecting VCs.**
- The **Areopagus** page lists every VC as a card: avatar, focus, dealbreakers and a voice preview.
- **Prepare** has a multi-select for which VCs to talk to.
- **Simulation** has its own separate multi-select for the panel.
- Both default to Lead Seed Fund, Angel Operator and Skeptical Partner. The last selection is remembered.
- The court orchestrator and interrupt policy only use the selected VCs. Each VC's `gap_lenses` filter which items from the TruthPack attack list it raises. A VC's `interrupt_tendency` adjusts the live-mode threshold.

**Creating custom VCs.**
- **Through code**: write a YAML or JSON file in `backend/data/areopagus/custom/` that follows the schema, or `POST /areopagus` with the JSON. Invalid files show a validation error in the UI.
- **Through natural language**: a "Create VC" box where the founder writes something like "A Bay Area SaaS fund partner obsessed with NRR who hates services revenue". Claude turns the description into a `VCPersona` using structured output. The founder sees a preview and editable form (pick a voice from a list), then a **test question** shows how the VC would open, and saving writes the YAML.
- Custom VCs can be edited, duplicated (including "fork a builtin") and deleted.

**Guardrails.** Whatever a persona spec says, the system rules sit above it and can't be overridden: source tagging, the audit, no valuation advice, no invented benchmarks. Spec text goes into a delimited persona block in the prompt and is treated as character description, not instructions.

API:
- `GET /areopagus`
- `POST /areopagus` (JSON spec)
- `POST /areopagus/generate` (natural language → spec preview)
- `PUT /areopagus/{id}`
- `DELETE /areopagus/{id}` (custom only)

## Agent architecture (technical)
Python `anthropic` SDK. Each VC runs its tool loop through the SDK **Tool Runner** (`client.beta.messages.tool_runner`, `@beta_tool`). **Our own Python orchestrator** owns the panel: memo, belief state, bidding, referee and audit. Re-read `python/claude-api/README.md` and `tool-use.md` from the claude-api skill when implementing.

**Every LLM call is stateless.** Each request is rebuilt from Neon: the stable prefix, then the persona, memo, belief state and the last N turns as user content. Thinking blocks are never replayed. This avoids the preserved-thinking "edited history" 400s on Opus/Sonnet 5.5, and lets any turn be replayed for debugging.

### Agent roster
| Agent | Model / effort | Shape | Output (pydantic) |
|---|---|---|---|
| **VC Mind: memo** | `claude-opus-5-5`, high | Tool Runner with read-only tools, then a final structured output | `Memo{thesis, hypotheses[{id, claim, lens, evidence[figure_id], severity, confidence}], mind_changers[], opening_question}` |
| **VC Mind: update and bid** | `claude-sonnet-5-5`, low | Single call with structured output, one per VC per founder answer, all VCs in parallel | `BeliefUpdate{deltas[{hyp_id, new_confidence, why}], bid 0–1, intent: follow_up/new_topic/jump_in/pass, target_hyp}` |
| **VC Voice: speak** | `claude-sonnet-5-5`, medium | Streaming, tools allowed (`get_metric`, `check_claim`) | Question text in the persona's style |
| **Claim extractor** | `claude-haiku-5-5`, low | Structured output | `Claim[]{text, metric, value, unit, period, is_forecast}` |
| **Deck reader** (pre-scan) | `claude-opus-5-5`, medium | PDF `document` block plus extracted slide text plus TruthPack summary | `SlideFinding[]{slide, claims[], visual_issues[], omissions[]}` |
| **Judge** | `claude-opus-5-5`, high | Structured output, independent of the VCs | Scores for dimensions 2–5, with rationale, what was good, what was missing, and a strong-answer rewrite |
| **Report writer** | `claude-opus-5-5`, high | Streaming, structured output | `Report` (all 9 sections) |
| **Auditor (LLM half)** | `claude-sonnet-5-5`, low | Structured output; runs on the report and on persona generation, not on live turns | `AuditFinding[]` |
| **Persona generator** | `claude-sonnet-5-5`, medium | Structured output | `VCPersona` |
| **TruthPack doc extractor** | `claude-opus-5-5`, medium | PDF `document` block | `Fact[]{name, value, unit, period, kind, page}` |

API rules from the claude-api skill:
- Thinking can't be disabled on Opus or Sonnet 5.5, so control depth with `output_config.effort`.
- Forced `tool_choice` returns a 400, so get JSON through `output_config.format` / `client.messages.parse()` and use `strict: true` on tools.
- Always check `stop_reason` (including `refusal`) before reading content.
- Enable server-side fallbacks (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) on Opus and Sonnet calls.
- All of this lives in one wrapper, `llm/client.py`.

### Tools
All tools are read-only and backed by code, with `strict: true`. **The VCs can't change the truth.**
- `get_metric(name, window?)`: returns a Figure with value, formula, inputs, kind and source.
- `list_metrics()`
- `check_claim(metric, value, unit, period?)`: returns a verdict (`matches`, `contradicts`, `unsupported` or `forecast_as_fact`) plus the Figure.
- `get_attack_list(lens?)`
- `forecast_gaps()`
- `list_missing_data(topic)`
- `define_term(term)`: from the glossary.
- `cite_source(topic)`: from `sources.yaml` only. This is how "no benchmark without a source" is enforced.
- Simulation only: `get_slide(n)`, `get_transcript(window)`, `get_ledger()`.

### Prompt structure and caching
Order (stable to volatile):
1. `tools`
2. System prompt: rules, the Appendix A case, the glossary and the Appendix D weak/strong examples.
3. Cache breakpoint.
4. Persona block (delimited) and memo.
5. Cache breakpoint.
6. Belief state, recent turns, and the intent for this turn.

Shared rules can't be overridden by persona text.

### Prepare turn loop (`court.py` + `referee.py`)
1. **Session start.**
   - The selected VCs' memos run in parallel (`asyncio.gather`, Opus) and are stored in Neon.
   - Meanwhile the UI shows "The Areopagus is reviewing your materials", with a progress line per VC.
   - Thinking runs with `display: "summarized"`, so the UI can show short reasoning snippets while the founder waits.
2. **Gap ownership.** Code assigns each attack-list item to the VC whose `gap_lenses` weight is highest. Items with severity ≥ 0.8 can be shared.
3. **Each founder answer.** The answer is stored, then these run in parallel:
   - (a) The claim extractor and `check_claim` produce the deterministic accuracy score.
   - (b) The Judge scores the answer.
   - (c) Every VC updates its beliefs and bids.
4. **Referee (pure code).** The next speaker is the VC with the highest of:

   `bid × lane_fit × fairness_decay(turns_since_spoke)`

   - The current VC gets a follow-up bonus if the answer was weak.
   - Follow-up depth is capped at 3.
   - Another VC may `jump_in` on the same thread if its bid beats the current VC's by more than 0.2.
   - All decisions are logged so the report can explain them.
5. **Speak.**
   - The chosen VC's turn streams over the WebSocket.
   - A sentence chunker sends each sentence through the deterministic audit, then to ElevenLabs TTS.
   - If a sentence fails the audit, the stream is dropped and the turn is regenerated once with the audit feedback. If it fails again, the VC falls back to its memo's `opening_question` for that hypothesis.
6. **Visibility.** Scores stay hidden during the session. Each VC card shows only a temperature glyph (warming, steady or cooling) based on its average hypothesis confidence. Full scores appear in the report.
7. **End.**
   - The session ends when the founder-configured question cap is reached (a setup slider from 6 to 20; the demo uses 6) or a time cap is reached, when every hypothesis is resolved (confidence below 0.2 or above 0.8), or when the founder ends it.
   - Then the report writer runs, and the LLM audit reviews the report.

### Simulation pipeline (`pitch.py`)
1. **Setup.**
   - The deck reader pre-scans the PDF: page images plus text, compared against the TruthPack. This seeds the claims ledger.
   - Memos are generated with the deck findings as extra input.
2. **While presenting.**
   - The STT final segment and the current slide go to the claim extractor (Haiku), then `check_claim`, then the ledger, which is pushed to the UI.
3. **Live mode.**
   - A `contradicts` claim, or a high-severity `unsupported` one, becomes an interrupt candidate.
   - The bid is computed in **code, not by an LLM**, to save latency: `severity × interrupt_tendency × lane_fit`.
   - The referee applies the 30-second cooldown and at most 1 interrupt per slide.
   - The winning VC speaks with `intent=interrupt`, kept to 2 sentences or fewer.
   - The founder's answer is judged, then the presentation resumes. Target latency from claim to voice is under 3 seconds.
4. **After mode.**
   - The transcript and the ledger go into the same bid/referee Q&A loop as Prepare, capped at 6–8 questions.

### Deterministic audit (`audit.py`)
- Extract every number with a regex and normalize units ($, K, M, %, months).
- Each number must match a Figure value within ±2%, or be quoted back as founder-said ("you said 10%").
- Pattern blocklist for valuation or investment recommendations.
- Benchmark phrases must come with a `cite_source` id.

### Storage: Neon Postgres (`db.py`, `asyncpg`, `DATABASE_URL`)
Tables:
- `truthpacks(id, facts jsonb, coverage jsonb, attack_list jsonb, confirmed_at)`
- `sessions(id, mode, truthpack_id, panel text[], interrupt_mode, deck jsonb, status, started_at, ended_at)`
- `memos(session_id, vc_id, memo jsonb)`
- `turns(id, session_id, seq, speaker, text, slide, t_offset, audit jsonb, referee jsonb)`
- `beliefs(session_id, vc_id, turn_seq, state jsonb, bid)`
- `scores(turn_id, accuracy, dims jsonb, rationale jsonb)`
- `claims(session_id, slide, t_offset, text, metric, value, status, figure_id)`
- `reports(session_id, report jsonb, markdown)`

Custom VCs stay as YAML files so they can be created through code; the natural-language path writes YAML too. Create a new Neon project `vicky` (ask the user first) and apply the schema with `schema.sql`.

## Source-of-truth document (required gate)
The source of truth is a session-level object, `TruthPack`, that both modes read. **The Pitch Simulation's Start button stays disabled until a TruthPack is submitted and confirmed.** Prepare uses the same TruthPack, so it is shared across modes.

Accepted inputs:
- **Structured (CSV/XLSX)**: parsed by `loader.py` straight into the metrics engine, with no LLM in the path.
- **Documents (PDF/DOCX/MD)**: text extracted (pypdf / python-docx). Claude then pulls figures into the `pack_facts` schema. Each figure carries a page reference and a historical/forecast/claim tag.
- **"Use sample: Tidewell data pack"**: loads CSV 01 plus `pack_facts.yaml`.

Confirm step:
- The founder reviews the extracted facts table and can edit or remove rows before confirming. Figures pulled from documents are labeled "from your document, p.X".
- Derived metrics are computed in code from the confirmed facts.
- A coverage checklist shows what the VCs can and can't probe, e.g. "No customer-level data → churn cohorts unavailable". VCs treat those gaps as questions ("You don't track pipeline. Why?").

New backend pieces:
- `truthpack.py` handles ingest, extraction and confirmation.
- `POST /truth/upload`, `POST /truth/confirm`.
- `/pitch/start` returns 409 without a confirmed TruthPack.

Home-hitting questions: on confirmation, the truth layer pre-computes a **ranked attack list**. It ranks claim gaps, forecast-vs-history gaps, concentration, runway risk and missing data by severity. Each VC draws from this list according to their persona's priorities, so questions target the founder's actual weak spots.

## Frontend design: black and white, minimalist luxury
Load the `frontend-design` skill before building the UI.
- **Typography**: JetBrains Mono everywhere (Google Fonts), using the weights 300, 400, 700 and 800. Use wide letter-spacing on small uppercase labels and large, tight numerals for KPIs.
- **Palette**: pure black `#000` and white `#fff`, plus two greys (`#111` for surfaces, `#8a8a8a` for muted text). No accent colour. State is shown with weight, inversion and hairlines, not colour: a contradicted claim is an inverted black chip, a matched claim is an outlined chip.
- **Layout**:
  - Generous whitespace and 1px hairline rules
  - No shadows, no rounded corners (or at most 2px)
  - Grid-aligned
  - Restrained motion: fades and a typewriter reveal for VC lines
- **Charts**: Recharts in monochrome. Series are told apart by solid, dashed and dotted lines and by grey levels. Forecast data is always dashed, actuals solid.
- **Landing page** (`/`):
  - The **JUNE** logo (copied from `june-logo-files-*/`) next to a new **VICKY** wordmark drawn to match. It is an SVG in the same heavy geometric sans, all caps, with one cut or notched letterform echoing the sliced "E" in JUNE (for example a notch in the "K" or "Y").
  - Lockup: `JUNE  /  VICKY`, then the tagline "Your AI venture capitalist. Know your numbers before they do."
  - Three entry cards: **Prepare**, **Simulate** and **Areopagus**.
  - Below them, a short "how it works" strip: Source of truth → Areopagus → Grilling → Feedback.
  - Footer: "Synthetic data. No investment advice."
- **App shell**: a top bar with the JUNE / VICKY lockup, tabs Prepare · Simulate · Areopagus · Reports, and a TruthPack status pill (`NO SOURCE OF TRUTH` inverted until one is confirmed).
- **Areopagus cards**: a monochrome geometric avatar per VC, its name, a one-line lens and its signature move in mono.

## Mode 1: Prepare
1. **Data intake**: the Tidewell pack is preloaded, with an upload area for more CSVs. A checklist shows which files are present or missing.
2. **Auto dashboard**: built with Recharts from `dashboard.py`. A fixed set of charts:
   - MRR and growth rate
   - Revenue mix
   - Gross margin booked vs including customer success
   - Burn and runway
   - S&M spend vs new customers (CAC)
   - Opex by department

   Also KPI tiles with source chips and a "show calculation" popover. The **Deck claims vs reality** table sits beside the charts.
3. **VC Court** (text chat, with optional TTS playback and optional mic answers via STT):
   - The founder first picks which Areopagus VCs to prepare against. Builtin and custom VCs both appear in the list.
   - The court opens with each selected VC's top concern, taken from the attack list and filtered by that VC's `gap_lenses`.
   - VCs bid for the next turn and a code referee picks the speaker (see Agent architecture).
   - Each VC asks follow-ups up to 2–3 levels deep when an answer is weak or unsupported.
   - Each founder answer is scored in the background and stays hidden until the report. After the session, every question in the report has a "strong answer" rewrite in which every number is cited.

## Mode 2: Pitch Simulation
1. **Setup** (requires a confirmed TruthPack): upload a PDF deck, which pdf.js renders. Before presenting, the deck is pre-scanned against the TruthPack, so the VCs arrive already knowing which slides overstate the numbers. The backend extracts each slide's text with pypdf. Choose the simulation panel from Areopagus (selected separately from Prepare) and set the toggle **Interrupt: Live / After**.
2. **Present**:
   - The mic streams to ElevenLabs realtime STT. The browser connects with a short-lived token from `voice.py`, so the API key stays on the server.
   - Each finalized transcript segment is sent over a WebSocket to `/pitch/{id}`, tagged with the current slide number.
3. **Claim extraction** (runs in both modes): Haiku pulls numeric and factual claims from each segment and its slide text. Each claim is checked against the truth layer and goes into a **claims ledger** with a status: matches, contradicts, unsupported or forecast-presented-as-fact.
4. **Live mode interrupt policy**:
   - Interrupt only on `contradicts`, or on a high-severity `unsupported` claim.
   - At most 1 interruption per slide and 30 seconds of cooldown.
   - When it fires, the UI pauses capture, the persona's question plays through ElevenLabs TTS, the founder answers by voice and gets scored, then presenting resumes.
5. **After mode**: at the end, the full transcript, slide text and claims ledger go to the court. The court runs a Q&A round of 6–8 questions, prioritizing ledger issues, through TTS and STT.
6. Both modes end in the **report**.

## Scoring (`scoring.py`)
Each answer and each pitch is scored 0–5 on five dimensions:
1. **Financial accuracy**: deterministic, based on ledger matches versus contradictions and on numbers in answers checked against the truth layer.
2. **Evidence & transparency**: cites how a number was calculated, admits the weak spot, separates forecast from actuals.
3. **Clarity**: plain language, direct answer first.
4. **Composure under follow-up**: whether the second- and third-level answers hold up.
5. **Investor-fit**: weighted by the persona's priorities.

The LLM judge scores dimensions 2–5 with a rubric that uses Appendix D's strong answers as anchors. Dimension 1 is computed in code.

**Extensive feedback report**: generated after **every** Prepare session and **every** Simulation session. Saved as JSON and shown on `/report/{session_id}`, with a Markdown export.
1. **Readiness verdict and score summary**: overall score, a radar chart of the 5 dimensions, and change versus the previous session if there is one.
2. **Per-VC verdict**: in each persona's voice, e.g. "Would I take a second meeting? No, because…", tied to that persona's priorities.
3. **Question-by-question breakdown**: the question asked, the founder's answer (transcript), the score per dimension, what was good, what was missing, the correct figure from the TruthPack with its calculation, and a **model strong answer** that cites its numbers.
4. **Claims ledger** (Simulation): every claim made, with slide and timestamp, the TruthPack value, and a status.
5. **Slide-by-slide notes** (Simulation): where each slide overstated or left something out, and suggested rewording.
6. **Delivery notes** (Simulation): talk time per slide, filler words, and answers that dodged the question. These come from transcript stats and need no audio analysis.
7. **Knowledge gaps**: finance concepts the founder stumbled on, with plain-language glossary explanations (Appendix I) and links to Appendix F sources.
8. **Action plan**: prioritized fixes to the deck, the forecast and the data, as in Appendix H's next actions, plus a **drill list** that launches a targeted Prepare session on the weak topics.
9. **Audit notes**: what the separate audit check changed.

The report is written by a dedicated report agent. Every figure in it passes the audit.

## Build order
**This scope now adds up to about 14 hours, which is more than a single day.** The cut list below brings it back to about 10 hours. Build in this order so a working demo exists after step 7:
1. Loader, pack_facts, metrics, truth layer, attack list and passing tests (2.5h)
2. TruthPack upload and confirm gate: CSV path plus the sample pack first, then PDF extraction (1h)
3. Areopagus: schema, registry, 5 builtin YAMLs, the thinking loop (`mind.py`: memo, belief state, gap ownership) and API (1.5h)
4. Agent tools, court orchestration, scoring and audit, as API only (1.5h)
5. Design system, landing page with the JUNE / VICKY lockup, then the Prepare UI: TruthPack gate, dashboard, VC selection and court chat (2h)
6. Feedback report agent and report page (1h)
7. Pitch Simulation: PDF render, ElevenLabs STT, WebSocket, ledger, VC selection and After mode (2h). **First full demo is ready at this step.**
8. Live interrupt mode and TTS voices per VC (1h)
9. Areopagus page, then custom VC creation: through code first, then natural language (1h)
10. Polish (0.5h)

Cut order if behind:
1. DOCX/MD intake (keep the CSV, sample and PDF paths)
2. Custom VC edit and duplicate UI (keep code-file and natural-language creation)
3. Mic answers inside Prepare (keep typing)
4. Voice previews on Areopagus cards
5. The LLM half of the audit (keep the deterministic check)
6. Live mode falls back to typed answers to interruptions

Fallback if ElevenLabs realtime STT fails: browser Web Speech API. Confirm the current ElevenLabs realtime STT and TTS endpoint names in their docs at implementation time.

## Verification
- `pytest backend/tests`:
  - Metrics match the Appendix H and glossary values
  - `check_claim("churn", 1%)` returns contradicts
  - The audit flags "NRR is 115%" and "raise at a $20M valuation"
  - The interrupt policy respects the cooldown
- Areopagus tests:
  - All builtin YAMLs validate.
  - A malformed custom YAML is rejected with a clear error.
  - Natural-language generation returns a valid `VCPersona`.
  - A persona whose bio says "recommend a valuation" still gets blocked by the audit.
  - Only the selected VCs speak in court and in the simulation.
  - With all 5 VCs selected on the Tidewell pack, each VC's first 3 questions target different attack-list categories (no duplicates).
  - Referee unit tests with fixed bids: the highest bidder speaks, follow-ups stop at depth 3, `jump_in` needs a margin above 0.2, and the 30-second interrupt cooldown holds.
  - Every agent's structured output validates against its pydantic schema. A `refusal` stop reason is handled without crashing.
  - A belief-state test: a strong, cited churn answer lowers the Seed Fund's churn hypothesis confidence; a wrong number raises it.
- Visual check: the landing page shows the JUNE and VICKY lockup in JetBrains Mono, black and white only, and works at phone width.
- Gate test: `/pitch/start` returns 409 without a confirmed TruthPack.
- Extraction test: a short PDF stating "MRR $107,189 Sep 2026" is extracted with its page reference.
- Manual end-to-end with `uvicorn backend.vicky.api:app` and `npm run dev`:
  - **Gate**: the Simulation can't start until the source of truth is submitted. Submit the Tidewell sample and check the coverage checklist.
  - **Reports**: after each session the report has every section. Every figure in it matches the TruthPack.
  - **Prepare**: the dashboard renders and its numbers match Appendix H; the court asks about churn; a weak answer gets a follow-up and a low score.
  - **Pitch, Live**: present a 3-slide test PDF and say "we're growing 10% a month". An interruption should play in a VC voice and the ledger should show `contradicts`.
  - **Pitch, After**: the same talk produces a post-pitch Q&A and a full report.
  - Ask "what valuation should we raise at?" → the app declines and explains how valuation and SAFE conversion work.
- Environment: `ANTHROPIC_API_KEY` (or an `ant auth login` profile), `ELEVENLABS_API_KEY` and `DATABASE_URL` (Neon).

## Open items
- Ask the organizers for CSVs 02–10, the xlsx and Appendix J.
- Pick 5 ElevenLabs voice IDs, one per persona.
