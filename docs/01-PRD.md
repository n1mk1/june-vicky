# Vicky — Product Requirements Document (PRD)

| | |
|---|---|
| Product | **Vicky**, June Analytics' AI venture capitalist (JUNE × VICKY) |
| Team | Catalyst hackathon, Team 18 (solo build) |
| Version | 1.0 — 17 Oct 2026 |
| Demo | Within 2 weeks of this date, hosted on Render |
| Companion docs | [02-TRD](02-TRD.md) · [03-UI-UX](03-UI-UX-DESIGN.md) · [04-App flow](04-APP-FLOW.md) · [05-Backend schema](05-BACKEND-SCHEMA.md) · [06-Implementation plan](06-IMPLEMENTATION-PLAN.md) · source plans [VICKY_PLAN.md](VICKY_PLAN.md) · [BACKEND_PLAN.md](BACKEND_PLAN.md) |

---

## 1. Summary

Vicky is an AI venture capitalist who prepares startup founders for fundraising. A founder uploads their own financial source of truth (CSV/XLSX in any layout, a PDF/DOCX, or figures typed in chat), and Vicky:

1. **Analyzes the numbers** — computes every metric in code, builds live dashboards, and lists the weak spots investors will attack first.
2. **Prepares the founder** — chairs a panel ("the Areopagus") of distinct AI investors who grill the founder in a text court, score every answer, and coach.
3. **Simulates the pitch** — the founder presents a PDF deck out loud; VCs with their own voices interrupt live or question afterwards, checking every spoken claim against the data.

Every session ends in a scored, cited feedback report with an action plan and drills.

The challenge sponsor's bar (brief §05 and Appendix G of the supporting pack): numbers come from code, every figure is sourced, historical is separated from forecast, missing data is reported as missing, a separate check audits the output, and **no valuation or investment advice is ever given**.

## 2. Problem

From the challenge brief (June Analytics, Team 18):

> "How can AI help startup founders understand their financials, prepare for tough investor questions, and confidently pitch their business?"

Founders like Craig and Jennifer (Appendix A: Tidewell Systems, Toronto, $1.29M ARR, raising $4M seed) are strong engineers with no finance background. Their draft deck makes nine claims; four would not survive a first investor meeting. Their pain:

| Pain (brief §03) | What founders do today | Why that fails |
|---|---|---|
| Limited financial expertise | Ask a general chatbot | One-shot answers, no access to their actual data, invents benchmarks |
| Unrealistic assumptions | Build a forecast in a spreadsheet over two weekends | Nobody tests the assumptions against history |
| Different investors, different priorities | Rehearse with friends | Friends ask soft questions, don't follow up three levels deep |
| Lack of preparation | Read "top 20 investor questions" lists | Not personalized to their weak spots |
| Financial complexity | Skip the hard metrics | Caught out live on churn, NRR, CAC payback |
| No access to expertise | Can't afford a fundraising coach | — |

The sponsor explicitly wants "deep agentic skills that go beyond the one-shot solutions that a general model can present."

## 3. Goals and non-goals

### Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | Founder preparedness improves across sessions | Readiness trend in Reports; weakness ledger shrinks |
| G2 | Every number shown is accurate and traceable | 100% of figures in agent output resolve to a code-computed `Figure` with a source (grounding eval) |
| G3 | Investors feel real and distinct | Blind judge identifies the archetype from a transcript (distinctness eval); no VC concedes without evidence |
| G4 | Finance becomes accessible | Plain-language explanations with glossary terms, cited sources, "why this was asked" |
| G5 | Feedback is actionable | Each question has a score, what was missing, the correct figure with formula, and a strong-answer rewrite |
| G6 | Trust and responsible AI | Audit blocks uncited numbers, uncited benchmarks and any valuation/investment advice |
| G7 | Startup-agnostic | Works on any founder's upload, not only the Tidewell sample (second synthetic fixture enforces it) |

### Non-goals (v1)

- No sign-up, multi-tenant identity, or billing. One shared demo workspace behind an access code.
- No valuation recommendation, no "invest/don't invest", no personalized financial advice (hard rule, enforced in code).
- No replication of June's existing platform (Franco the Finance Officer, Rocco the Risk Officer). Vicky only.
- No real company data. Synthetic data only (brief §05 Data Privacy); the Tidewell pack is the sample.
- No SEO "how-to article" (brief bonus) in v1; listed as a stretch.
- No mobile-first native app. Responsive web.

## 4. Users and personas

| Persona | Needs | Primary surfaces |
|---|---|---|
| **Founder with little finance experience** (Jennifer, CEO; Craig, CTO) | Know their numbers, find the holes in their forecast, rehearse under pressure, get a concrete fix list | Dashboard, Preparation, Simulation, Reports |
| **Founder who already knows finance** | Stress-test a specific claim, run a tough panel, build a custom investor they expect to meet | Areopagus builder, Simulation live mode |
| **Hackathon judge / June Analytics reviewer** | See accuracy, realism, interactivity, responsible AI in a 5-minute demo | Landing → sample → dashboard → court → report |

## 5. Product principles (enforced in code, not only in prompts)

1. **Numbers come from code.** The metrics engine computes every figure. Agents only choose what to compute, cite and chart.
2. **Citation first.** Every figure carries a source (CSV rows, PDF page, data-pack summary, or a curated public source with URL). The UI renders footnotes; reports end with a Sources section.
3. **Historical ≠ forecast ≠ founder claim.** Every `Figure` has a `kind`; the UI shows it (solid vs dashed lines, "summary" badges, claim chips).
4. **Missing is a valid answer.** A coverage checklist says what the data cannot support and what upload would unlock it; VCs turn gaps into questions.
5. **A separate check reviews every answer.** Deterministic audit on every VC, Vicky and report sentence; an LLM audit on reports.
6. **No valuation or investment advice.** Pattern blocklist in the audit, applied to every agent. Vicky explains how SAFEs convert and how dilution works, never what the company is worth.
7. **Nothing is hard-coded to one company.** No metric, threshold, question or UI string references Tidewell. The sample loads through the same path as any upload.
8. **Agents are stateless per call.** Memos, beliefs, turns and claims live in Postgres; every call is rebuilt from them.

## 6. Scope: the five tabs

Navigation: **Dashboard · Preparation · Simulation · Areopagus · Reports**, plus the landing page and a report page.

### 6.1 Landing and access
- Access gate: the `ACCESS_CODE` is entered once; a signed HTTP-only cookie follows.
- Landing hero (existing v1 template): 3D VICKY mark, headline "Know your numbers before they do.", mode links Insights · Prep · Sim, a prompt bar with attach.
- Prompt bar actions: attach a file to the source of truth or type a question (no sample companies are offered; data comes in through the knowledge base). Haiku intent routing sends `data`/`dashboard` questions to the Dashboard and `practice` to Preparation.
- Footer line: "Synthetic data. No investment advice."

### 6.2 Source of truth (TruthPack) and engagement
- **Engagement** = one company's workspace: profile, TruthPack, datasets, dashboards, sessions, reports, founder memory. The workspace holds one engagement at a time; confirming a new TruthPack starts a new engagement and the previous stays listed under Reports.
- **Company profile** (collected by Vicky in chat on first upload, or inferred and confirmed): name, country, currency, fiscal year start, stage, round type/size, business model (`recurring | other`), data granularity (month/quarter).
- **Inputs accepted:**
  - CSV/XLSX in any layout → column profiling → Claude proposes a mapping to the canonical model → **founder confirms or edits the mapping** (low-confidence rows highlighted; unmapped columns kept as raw data).
  - PDF/DOCX/MD → facts extracted with page-level citations, verified in code against the document text; unverifiable facts flagged.
  - Typed figures in chat ("our MRR is $80K") → pending facts tagged `founder_stated`; treated as claims, not records.
  - "Use a sample" → loads a fixture through the exact same path.
- **Confirm step:** founder reviews the facts table (edit/remove rows), sees the coverage checklist, and confirms. Simulation is gated on a confirmed TruthPack (`409` otherwise).
- **Attack list:** on confirm, the truth layer ranks weak spots across 12 lenses (claims, forecast, retention, unit_economics, concentration, runway, governance, market, team, product_tech, terms_cap_table, impact) with sourced thresholds.

### 6.3 Dashboard (Analyze the Numbers)
- **Default dashboard** on confirm (wireframe layout): gross-margin ring (as booked vs including customer success), ARR card with growth/burn/runway, **readiness orb** (3D, score from the last session), MRR/burn trend chart, "What they'll ask first" attack list.
- **Metric set by availability:** recurring-revenue set (ARR, MRR growth, NRR/GRR, CAC payback, burn multiple, magic number) when recurring revenue exists; generic set (revenue growth, gross margin, burn, runway, concentration, opex mix) always. Missing-data tiles name the upload that unlocks a metric.
- **Vicky's dashboard chat** (CopilotKit + AG-UI): "burn excluding SR&ED as % of revenue by quarter" → Vicky adds an ECharts widget; code computes the series; a "Widget added" card offers Undo. Missing data → Vicky says what is missing and adds nothing.
- **Interaction:** linked tooltips, data zoom/brush that moves every chart, legend toggles, click-to-explain (formula, inputs, source rows), drag/resize/pin, "Ask about this".
- **Realtime:** the dashboard is shared across tabs; edits appear everywhere via WebSocket.
- Source chips on every figure; "summary"/"founder said" badges on non-historical figures.

### 6.4 Preparation (Prepare the Founder) — the court
- **Roster** (left column): a fixed, non-deselectable **Chair** card for Vicky, then the five built-in VCs (all five seated by default; up to 5 seated), custom VCs, and a "+" to describe a new investor. Each card shows the glyph, firm, interest temperature (warming/steady/cooling) and a speaking dot.
- **Memos:** at session start every seated VC writes a private memo (thesis, 3–5 weakness hypotheses with Figure evidence, mind-changers, opening question); summarized-thinking snippets stream while the founder waits ("Socrates is stress-testing growth…").
- **Chair:** Vicky orchestrates, reviews, validates and scores. She sets the agenda from the attack list and the founder's goals, seats and introduces the panel, decides who speaks with what intent after each answer, can interject (end a thread, switch topic, coaching time-out), and closes with a debrief. She **reviews every drafted VC line before it is spoken** (one question, in the VC's lane, not a repeat, not giving a knowledge answer away; code's checks always count) and sends a failing line back once for a rewrite. She **scores every answer** (the dimension bars; accuracy stays code's claim check).
- **Knowledge checks** (on by default, needs the search index from Fill dashboard): at session start, retrieval finds passages of the founder's own notes in each seated VC's lenses, and a recall question is written from each (its answer key is a verbatim span of the passage; tables and hub notes are skipped). Vicky schedules one every few questions (never right after a weak answer, at most a third of the cap); the VC asks it in their voice. Vicky verifies the answer against the key and a fresh retrieval over the answer: **Knew it · Partly · Contradicts notes · Missed · Not checked**, with the note quoted word for word and cited.
- **Turn loop:** founder answers (typed, optional mic) → claim extraction + `check_claim` (+ Vicky's knowledge verification on a knowledge check) → Vicky scores → all VCs update beliefs and bid in parallel → referee computes candidates → Vicky's chair decision (validated by code; falls back to the code pick) → chosen VC drafts the line (audited) → Vicky reviews it (one rewrite if sent back) → it is spoken. Follow-ups up to 3 deep; a VC may jump in when its bid beats the current speaker's by a margin.
- **No-concession rule:** a VC's concern only drops when the answer cites a matching Figure.
- **Coaching mode:** Coached (default in Prepare): after two weak answers on one hypothesis, a short time-out names the gap and points at the Figure without answering. Realistic: silent until debrief.
- **Feed** (centre): chat with filters Everything · Feedback & scoring · Slide design · Knowledge; score cards (by Vicky) with five dimension bars and a claim chip; knowledge-check cards with Vicky's verdict and the cited note; a line Vicky sent back shows her note; inline footnotes on every number.
- **Questions & answers** (right): every question asked, the answer, score, claim status; mark to Repeat or Study; "Drill N selected" launches a targeted session.
- Session ends at the question cap (6–20, founder-set), time cap, when every hypothesis resolves, or when the founder ends it. Then the report runs.

### 6.5 Simulation (Simulate the Pitch)
- Requires a confirmed TruthPack. Upload a PDF deck; pre-scan compares each slide's claims to the TruthPack (ledger seeded before the founder speaks).
- Choose the panel (separate from Prepare) and the toggle **Interrupt live / Questions after**.
- **Present:** mic → ElevenLabs realtime STT (short-lived token; the API key stays server-side). Each finalized segment is tagged with the current slide and run through claim extraction and `check_claim`; the claims ledger updates live.
- **Live mode:** a `contradicts` claim or a high-severity `unsupported` one becomes an interrupt candidate; code proposes, Vicky approves or vetoes within 1 s (code decides alone on timeout); at most one interrupt per slide, 30 s cooldown; the VC speaks ≤ 2 sentences in their own TTS voice; the founder answers by voice and is judged; presenting resumes. Target claim-to-voice latency under 3 s.
- **After mode:** transcript + ledger feed a post-pitch Q&A chaired by Vicky, 6–8 questions.
- **Views:** Slide view (rendered deck, claim check per slide, slide strip with status bars) or Performance feedback (feed). Right column: scoring and metrics (overall, five dimensions, claims ledger counts, talk time, filler words, seconds per slide).

### 6.6 Areopagus (the investor registry)
- Cards for the 5 built-in investors (name, archetype, main lens, signature move, kits, voice preview) and every custom VC in the workspace.
- **Built-in roster**, named for Greek philosophers: Aristotle (Lead Seed Fund), Thales (Angel Operator), Xenophon (Strategic Investor), Plato (Government-Backed Fund, country-aware) and Socrates (Skeptical Partner). The other archetypes live on as builder templates and question banks.
- **No-code builder:** describe an investor in natural language → structured `VCPersona` preview → edit form (name/archetype/cheque role; lens-weight sliders that pick kits; tone/interrupt/depth sliders; dealbreaker and seed chips; signature move; voice picker) → "How would they open?" test memo on the current TruthPack → save (shared in the workspace). Edit, duplicate, delete custom; built-ins read-only but forkable (a fork keeps the archetype's method). YAML/JSON import/export.
- Guardrails: persona text is character description, never instructions; field caps; audit applies to every VC.

### 6.7 Reports
- Lists engagements (current and past) and their sessions. Each report (`/report/{id}`):
  1. Readiness verdict and score summary (overall, radar of five dimensions, change vs previous session)
  2. Per-VC verdict in each persona's voice ("Would I take a second meeting?")
  3. Question-by-question breakdown: question, why it was asked, answer, scores per dimension, what was good, what was missing, the correct Figure with formula, a cited strong-answer rewrite
  4. Claims ledger (Simulation): every claim, slide, timestamp, data value, status
  5. Slide-by-slide notes (Simulation)
  6. Delivery notes (Simulation): talk time per slide, filler words, dodged answers
  7. Knowledge gaps with glossary explanations and sources
  8. Action plan: prioritized fixes to deck, forecast and data; drill list that launches a targeted Prepare session
  9. Audit notes: what the separate check changed
  10. Sources: numbered list of every CSV range, page and URL cited
- Markdown export. Vicky writes synthesis and action plan; the Judge's scores and the audit stay independent.

### 6.8 Founder memory
- Weakness ledger by lens, past answers and scores, rewrites seen, drills done — exposed to agents as `recall(topic)` ("Last session you said 10%"). Drives the readiness trend and spaced drills.

## 7. Scoring

Each answer and each pitch is scored 0–5 on five dimensions:

| Dimension | Who scores | Basis |
|---|---|---|
| Financial accuracy | Code | Ledger matches vs contradictions; numbers in answers checked against the truth layer |
| Evidence & transparency | Judge (Opus 5.5) | Cites how a number was calculated, admits the weak spot, separates forecast from actuals |
| Clarity | Judge | Plain language, direct answer first |
| Composure under follow-up | Judge | Second- and third-level answers hold up |
| Investor fit | Judge, weighted by persona | What this investor cares about |

Anchors: Appendix D's 15 weak/strong answer pairs. Scores stay hidden during a session (temperature glyph only) and appear in the report.

## 8. Functional requirements (acceptance)

| ID | Requirement | Acceptance test |
|---|---|---|
| FR-1 | Metrics on the Tidewell fixture match Appendix H | ARR $1.29M; CMGR ≈ 9.0% (12 mo) and ≈ 5.0% (last 2–3 mo); margins 92% / 74–78%; burn ≈ $58K; burn multiple 0.6 / 0.8 ex-SR&ED |
| FR-2 | Any-layout ingestion | Harbor Labs fixture (quarterly, wide, different column names) maps ≥ 90% of columns correctly; metrics compute; cohort NRR/GRR appear; tax-credit figures report as missing |
| FR-3 | Availability-aware metrics | Services fixture: only the generic set runs; SaaS metrics are `MissingFigure`s |
| FR-4 | Startup-agnostic | Grep test: no "Tidewell" string outside `data/samples/` and tests |
| FR-5 | Claim checking | `check_claim("churn", 1%)` → `contradicts` with the Figure |
| FR-6 | Audit | Flags "NRR is 115%", "raise at a $20M valuation", and any uncited benchmark; the turn is regenerated once |
| FR-7 | Citations | PDF stating "MRR $107,189 Sep 2026" yields a fact with page 1 and verified `cited_text` |
| FR-8 | Court distinctness | 5 seated VCs' first questions hit 5 different lenses; Aristotle challenges a contradicting answer; Xenophon records a missed ROFR; a valuation line is blocked and regenerated; Vicky sends back a repeated question; a knowledge answer is verified against the cited note |
| FR-9 | Chair | A `ChairDecision` breaking a cooldown or arriving after 1.5 s falls back to the code pick; Coached time-out contains no new figure |
| FR-10 | Simulation gate | `/pitch/start` returns 409 without a confirmed TruthPack |
| FR-11 | Live interrupt | Say "growing 10% a month" on a 3-slide deck → interruption in a VC voice; ledger shows `contradicts` |
| FR-12 | Dashboards | Vicky's "burn excluding SR&ED as % of revenue by quarter" adds a widget in two tabs; clicking a bar shows formula and source rows; "zoom to the last 6 months" moves every chart; layout persists |
| FR-13 | Builder | Description → valid persona → test question → saved and visible in another browser; forking Socrates keeps the pre-mortem |
| FR-14 | Access | `/api/v1/*` returns 401 without the access cookie |
| FR-15 | Responsible AI | "What valuation should we raise at?" is declined with an explanation of how valuation and SAFE conversion work |
| FR-16 | Resilience | Redeploy mid-session → WebSocket reconnects, session intact |

## 9. Non-functional requirements

| Area | Requirement |
|---|---|
| Latency | Founder answer → first VC token P50 < 3 s; live interrupt claim → voice < 3 s; chair decision ≤ 1.5 s (else code fallback) |
| Cost | `DAILY_USD_BUDGET` guard (default $5/day in development, raised for judging); max 5 seated VCs; memos cached per TruthPack + persona version; ≈ $2–2.5 per 3-VC Prepare session |
| Availability | Free tier while building; paid Render plans switched on the day before the demo (no cold starts during judging) |
| Data | Uploads ≤ 10 MB stored in Postgres (bytea); synthetic data only; Redis holds only ephemeral state |
| Security | Access code + signed cookie; per-IP rate limit; secrets only in env vars; ElevenLabs key never reaches the browser |
| Accessibility | Keyboard-navigable, ARIA roles on roster/tabs/feeds, `prefers-reduced-motion` respected, light and dark themes |
| Browser | Desktop (1440) and phone (390) layouts for every page |

## 10. Success metrics for the demo

Mapped to the brief's evaluation criteria:

| Criterion | Evidence we show |
|---|---|
| Usefulness to founders | A full cycle on an unfamiliar CSV: profile → mapping → dashboard → court → report with drills |
| Financial accuracy | Every figure footnoted; grounding eval at 100%; Appendix H numbers reproduced |
| Investor realism | 10 archetypes with coded methods; distinctness eval; no-concession rule; Vicky chairing |
| Interactivity | Live dashboards from chat, voice simulation with interrupts, multi-tab realtime |
| Responsible AI | Valuation question declined; audit notes in the report; "verify with an advisor" on country rules |

## 11. Risks and mitigations (product level)

| Risk | Mitigation |
|---|---|
| Only CSV 01 of the 10 data files is available; Appendix J missing | `pack_facts.yaml` transcribed from Appendices A–C labelled "data pack summary"; gaps become VC questions; organizers asked for the rest |
| Column mapping guesses wrong | Founder confirms every mapping; low-confidence rows highlighted; mappings reused on re-upload |
| Unusual data (non-recurring model, no monthly series) | Availability-aware metrics; generic set always runs; typed-figure path as last resort |
| Country rules wrong or stale | Only sourced rules ship; everything else is a question marked "verify with an advisor" |
| Shared workspace: one founder's actions affect everyone | One engagement at a time; new TruthPack starts a new engagement; access code limits who's in |
| Scope vs 4–5 days | Cut order in the implementation plan; never cut column mapping, availability-aware metrics or the citation audit |

## 12. Open items

- Create the Anthropic Console API key (billing + spend limit); confirm the ElevenLabs key; pick 11 voice IDs (10 VCs + Vicky).
- Ask organizers for CSVs 02–10, the xlsx and Appendix J (30 test scenarios).
- Author the Harbor Labs and services-co fixtures (seeded, known expected metrics).
- Decide what the stray file `0` is (parked in `brand/_unsorted/`).
- Stretch: SEO "how-to" article generated from a report (brief bonus); Lead Seed deep dive via code execution.
