# Vicky — Backend Schema

Version 1.0 — 17 Oct 2026. Companion to [02-TRD](02-TRD.md). Postgres 17 is the only durable store; Redis (Valkey) holds ephemeral state. Migrations live in `backend/migrations/NNNN_*.sql`, applied by `vicky.migrate` (idempotent, `pg_advisory_lock` on startup in the free tier, `preDeployCommand` on paid).

Conventions: `id uuid primary key default gen_random_uuid()`, `created_at timestamptz default now()`, `updated_at` maintained by trigger, soft state in enums, JSON documents validated by pydantic before insert. Everything company-specific carries `engagement_id`.

---

## 1. Entity overview

```
workspace (implicit, one)
 ├── vc_personas (custom VCs, workspace-wide)
 ├── sources (benchmark library, seeded from data/sources.yaml)
 └── engagements ──┬── company_profiles (1:1)
                   ├── uploads ──┬── datasets ── dataset_mappings
                   │             └── (documents → facts)
                   ├── truthpacks (facts, coverage, attack_list)
                   ├── dashboards ── widgets, dashboard_messages
                   ├── sessions ──┬── memos, beliefs, turns, claims, scores, chair_decisions
                   │              └── reports
                   ├── founder_memory
                   └── jobs
```

## 2. Tables

### 2.1 `engagements`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| status | enum `draft \| active \| archived` | exactly one `active` (partial unique index) |
| name | text | company name (denormalized from profile) |
| truthpack_id | uuid FK → truthpacks | current confirmed pack |
| created_at, confirmed_at, archived_at | timestamptz | |

### 2.2 `company_profiles`
| Column | Type | Notes |
|---|---|---|
| engagement_id | uuid PK/FK | 1:1 |
| name | text | |
| country | char(2) | ISO; selects geo playbook (`CA`, `US`, `GB`, else `generic`) |
| currency | char(3) | |
| fiscal_year_start_month | smallint | 1–12 |
| stage | enum `pre_seed \| seed \| series_a \| series_b_plus \| other` | |
| round_type | text | e.g. `priced_equity`, `safe` |
| round_size | numeric(14,2) | |
| business_model | enum `recurring \| other` | activates the SaaS metric set |
| granularity | enum `month \| quarter` | |
| inferred | jsonb | which fields were inferred vs confirmed |

### 2.3 `uploads`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| engagement_id | uuid FK | |
| filename, mime | text | |
| bytes | bytea | ≤ 10 MB (checked in API) |
| sha256 | text | dedupe |
| kind | enum `csv \| xlsx \| pdf \| docx \| md \| deck` | |
| status | enum `stored \| parsed \| extracted \| failed` | |
| error | text | |

### 2.4 `datasets`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| engagement_id, upload_id | uuid FK | |
| name | text | sheet/file name |
| period_axis | text | detected column, or `transposed` |
| granularity | enum `month \| quarter \| year \| none` | |
| columns | jsonb | `[{name, dtype, sample_values[], null_rate}]` |
| rows | jsonb | normalized long table `[{period, column, value}]` or wide rows; ≤ 50k cells |
| fingerprint | text | hash of column names, used to reuse mappings |

### 2.5 `dataset_mappings`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| dataset_id | uuid FK unique | |
| fingerprint | text indexed | reuse on re-upload |
| proposed | jsonb | `ColumnMapping[]` from Sonnet with confidence |
| confirmed | jsonb | founder-edited mapping |
| confirmed_at | timestamptz | |

`ColumnMapping = {source_column, canonical_field | null, unit, confidence 0–1, note}`

### 2.6 `truthpacks`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| engagement_id | uuid FK | |
| facts | jsonb | `Fact[]` (see §4) including founder_stated and document facts |
| figures | jsonb | cached `Figure[] + MissingFigure[]` computed at confirm; recomputed on change |
| coverage | jsonb | `[{group, metric_id, available bool, needs[]}]` |
| attack_list | jsonb | `[{id, lens, topic, detail, severity 0–1, figure_ids[], source_id?}]` |
| deck_claims | jsonb | from the latest pre-scan |
| version | int | bumps on every fact/dataset change |
| confirmed_at | timestamptz | null = pending |

### 2.7 `dashboards`, `widgets`, `dashboard_messages`
`dashboards`: id, engagement_id, name (`default`), layout jsonb (`[{widget_id, x, y, w, h, pinned}]`), time_range jsonb, version int (optimistic concurrency), updated_at.

`widgets`: id, dashboard_id FK, spec jsonb (`WidgetSpec`), spec_hash text, option_cache jsonb (ECharts option, nullable), provenance jsonb (`[{series, points[{period, value, formula, inputs, source}]}]`), status enum `ok | missing | error`, missing jsonb (`MissingFigure`), created_by enum `system | vicky | founder`, order int.

`dashboard_messages`: id, dashboard_id, role enum `founder | vicky | tool`, content text, tool_calls jsonb, citations jsonb, created_at. Append-only.

### 2.8 `vc_personas`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| slug | text unique | |
| spec | jsonb | `VCPersona` (validated) |
| base_archetype | text | built-in id when forked |
| version | int | bumps on edit; memo cache key |
| builtin | bool | always false here (built-ins come from the repo) |
| created_at, updated_at | | |

### 2.9 `sessions`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| engagement_id, truthpack_id | uuid FK | |
| mode | enum `prepare \| simulate` | |
| panel | text[] | persona ids (built-in slugs or uuids), ≤ 5 |
| settings | jsonb | `{question_cap, time_cap_s, coaching: coached\|realistic, interrupt_mode: live\|after, drills[]}` |
| deck_upload_id | uuid FK | simulation |
| deck | jsonb | `SlideFinding[]` from pre-scan + per-slide text |
| agenda | jsonb | chair's agenda `[{hypothesis_id, lens, owner_vc}]` |
| status | enum `starting \| live \| paused \| ended \| failed` | |
| started_at, ended_at | timestamptz | |

### 2.10 `memos`
session_id FK, vc_id text, persona_version int, truthpack_version int, memo jsonb (`Memo`), thinking_snippets jsonb, usage jsonb, PK (session_id, vc_id). Cache lookups also index (vc_id, persona_version, truthpack_version).

### 2.11 `turns`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| session_id | uuid FK | |
| seq | int | unique per session; append-only |
| speaker | text | `founder`, `vicky`, or vc_id |
| kind | enum `question \| answer \| interject \| coach \| debrief \| segment \| interrupt` | |
| intent | text | chair intent for VC turns |
| hypothesis_id | text | |
| text | text | final audited text |
| citations | jsonb | `[{marker, figure_id?, source_id?, formula, source}]` |
| slide | int | simulation |
| t_offset_ms | int | simulation |
| audit | jsonb | `{passed, regenerated, findings[]}` |
| usage | jsonb | |

### 2.12 `beliefs`
session_id, vc_id, turn_seq, state jsonb (`{hypotheses[{id, confidence, severity, last_evidence}]}`), bid numeric, intent text, target_hyp text, PK (session_id, vc_id, turn_seq).

### 2.13 `chair_decisions`
id, session_id, after_turn_seq, candidates jsonb (referee-ranked), decision jsonb (`ChairDecision`), valid bool, fallback bool, latency_ms int, reason text.

### 2.14 `claims`
id, session_id, turn_id FK, slide int, t_offset_ms int, text, metric text, value numeric, unit text, period text, is_forecast bool, status enum `matches | contradicts | unsupported | forecast_as_fact`, figure_id text, severity numeric. Index (session_id, status).

### 2.15 `scores`
turn_id PK/FK (the founder answer), accuracy numeric (code), dims jsonb (`{evidence, clarity, composure, investor_fit}` 0–5), rationale jsonb (`{good, missing, correct_figure, strong_answer, why_asked}`), judge_usage jsonb.

### 2.16 `reports`
id, session_id FK unique, engagement_id, report jsonb (`Report`, §4), markdown text, overall numeric, dims jsonb, delta_vs_previous numeric, audit_notes jsonb, sources jsonb (numbered), created_at.

### 2.17 `founder_memory`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| engagement_id | uuid FK | |
| kind | enum `weakness \| answer \| rewrite \| drill` | |
| lens | text | |
| topic | text | |
| payload | jsonb | e.g. `{session_id, question, answer, score, figure_id}` |
| severity | numeric | weaknesses |
| last_seen_at | timestamptz | |

`recall(topic)` queries by engagement + lens/topic, newest first.

### 2.18 `jobs`
id, engagement_id, session_id?, kind enum `memo | prescan | extract | report | persona_gen | audit`, status enum `queued | running | done | failed | stale`, payload jsonb, result jsonb, error text, attempts int, enqueued_at, started_at, finished_at. `stale` is set by a sweeper when `queued` exceeds its TTL (Key Value restart); the UI offers Retry.

### 2.19 `sources`
id text PK (e.g. `sacks_burn_multiple`), publisher, claim text, url, as_of date, business_model text[], stage text[], topic text[], verified bool. Seeded from `data/sources.yaml` at migration time; the YAML is the source of truth.

### 2.20 `spend` (optional mirror of Redis)
date PK, usd numeric, calls int — written at day end for reporting.

## 3. Indexes and constraints

- `engagements`: partial unique on `(status) where status='active'`.
- `turns`: unique `(session_id, seq)`; index `(session_id, speaker)`.
- `claims`: index `(session_id, status)`; `widgets`: unique `(dashboard_id, spec_hash)`.
- `founder_memory`: index `(engagement_id, lens, last_seen_at desc)`.
- `jobs`: index `(status, enqueued_at)`.
- FK cascades: deleting an engagement cascades everywhere below it (admin only; the UI never deletes).

## 4. JSON document shapes (pydantic, `llm/schemas.py` and `model/figures.py`)

```jsonc
// Figure
{"id":"arr","label":"ARR","value":1286268,"unit":"cad","period":"2026-09",
 "formula":"Sep 26 recurring revenue × 12","inputs":[{"figure_id":"mrr"}],
 "source":{"kind":"csv","ref":"rows 25","dataset_id":"…"},"kind":"historical"}

// MissingFigure
{"id":"nrr","needs":["cohort_mrr"],"reason":"Upload a cohort table to unlock NRR/GRR"}

// Fact (truthpacks.facts[])
{"id":"…","name":"cash_balance","value":483270,"unit":"cad","period":"2026-09",
 "kind":"historical","source":{"kind":"pdf","ref":"p.6","cited_text":"Cash in the bank $483,270","verified":true}}

// WidgetSpec
{"template":"combo_bar_line","title":"Burn ex-credits as % of revenue",
 "series":[{"ref":"pct_of(burn_ex_non_dilutive, revenue.total)","label":"Burn %"}],
 "window":{"from":"2024-Q4","to":"2026-Q3"},"group_by":"quarter","compare":null,
 "presentation":{"stack":false,"smooth":false,"dual_axis":false,"labels":true,"mark_lines":[],"sort":null,"unit":"pct"}}

// VCPersona
{"id":"mark","name":"Mark","archetype":"skeptical_ic_partner","bio":"…","cheque_role":"votes_in_ic",
 "priorities":{"concentration":0.9,"claims":0.9,"forecast":0.6,"retention":0.5},
 "style":{"tone":"blunt","interrupt_tendency":0.8,"follow_up_depth":3,"aggression":0.8},
 "signature_move":"Pre-mortem chain","question_seeds":["…"],"dealbreakers":["…"],
 "scoring_weights":{"accuracy":0.3,"evidence":0.3,"clarity":0.1,"composure":0.2,"investor_fit":0.1},
 "voice_id":"…","base_archetype":null,"kits":["RedTeam"],"builtin":true}

// Memo
{"thesis":"…","hypotheses":[{"id":"h1","claim":"Growth is decaying","lens":"forecast",
 "evidence":["cmgr_12m","cmgr_3m"],"severity":0.9,"confidence":0.7}],
 "mind_changers":["…"],"opening_question":"…"}

// BeliefUpdate
{"deltas":[{"hyp_id":"h1","new_confidence":0.75,"why":"no figure cited"}],
 "bid":0.82,"intent":"follow_up","target_hyp":"h1"}

// ChairDecision
{"action":"call_on","vc_id":"mark","intent":"follow_up","hypothesis_id":"h1","note":"push on the last-3-month rate"}

// Claim
{"text":"growing 10% a month","metric":"cmgr","value":0.10,"unit":"pct","period":"L12M","is_forecast":false}

// Report (reports.report)
{"verdict":{"readiness":"not_ready","overall":3.1,"dims":{…},"delta":-0.4},
 "per_vc":[{"vc_id":"james","verdict":"…","second_meeting":false}],
 "questions":[{"turn_id":"…","question":"…","why_asked":"…","answer":"…","scores":{…},
               "good":"…","missing":"…","correct_figure":{Figure},"strong_answer":"…","citations":[…]}],
 "ledger":[{Claim + status + figure}],"slides":[{"slide":2,"note":"…","reword":"…"}],
 "delivery":{"talk_time_s":402,"fillers":14,"slide_seconds":[38,112,74,96,82],"dodged":[…]},
 "knowledge_gaps":[{"term":"NRR","text":"…","source_id":"…"}],
 "action_plan":[{"priority":1,"text":"…","drill_lens":"forecast"}],
 "audit_notes":[{"changed":"…","why":"…"}],
 "sources":[{"n":1,"kind":"csv","ref":"…"},{"n":2,"kind":"url","url":"…","publisher":"…"}]}
```

## 5. Redis (Valkey) keys — ephemeral only

| Key | Type | TTL | Use |
|---|---|---|---|
| `arq:queue` (default) | list/zset | — | arq job queue (`noeviction`) |
| `vicky:session:{id}` | pub/sub | — | turn deltas, chair decisions, memo snippets, ledger, interrupts |
| `vicky:dashboard:{id}` | pub/sub | — | widget/layout diffs with version |
| `vicky:pitch:{id}` | hash | 6 h | current slide, last interrupt time, per-slide interrupt count, live transcript tail |
| `vicky:series:{spec_hash}:{truthpack_version}` | string (json) | 24 h | evaluated series cache |
| `vicky:memo:{vc_id}:{persona_version}:{truthpack_version}` | string | 7 d | memo cache pointer (memos also in Postgres) |
| `vicky:rl:{ip}` | counter | 60 s | rate limit |
| `vicky:spend:{YYYY-MM-DD}` | float | 48 h | daily USD estimate |
| `vicky:lock:migrate` | — | — | not used; Postgres advisory lock instead |

Losing all Redis data is harmless: queued jobs become `stale` and retryable; everything else recomputes.

## 6. Repository data files (`backend/data/`)

| Path | Content |
|---|---|
| `samples/tidewell/income_statement_monthly.csv` (+ README with the original name), `pack_facts.yaml` | Sample fixture; facts transcribed from Appendices A–C labelled `pack_summary` with appendix/page refs |
| `samples/harbor-labs/` | Synthetic US SaaS, quarterly, wide layout, different column names, no tax credits, cohort table; seeded with known expected metrics |
| `samples/services-co/` | Tiny non-recurring fixture; only the generic metric set applies |
| `sources.yaml` | Benchmark library (see `sources` table) |
| `glossary.yaml` | Appendix I terms, plain-English definitions |
| `questions.yaml` | Appendix D 15 questions with weak/strong anchors (Judge rubric) |
| `playbooks/*.md`, `playbooks/geo/{CA,US,UK,generic}.md` | Metric traps, term-sheet mechanics, deck heuristics, per-archetype question banks, country rules ("verify with an advisor") |
| `../vicky/areopagus/builtin/*.yaml` | 10 built-in persona specs |

## 7. Event envelopes

WebSocket and pub/sub share one envelope:

```jsonc
{"type":"vc.turn.delta","session_id":"…","version":812,"ts":"…","payload":{"turn_seq":12,"speaker":"mark","text":"…"}}
```

Types: `memo.snippet`, `chair.decision`, `vc.turn.delta`, `vc.turn.done`, `coach.timeout`, `score.ready` (coached only), `ledger.update`, `interrupt`, `widget.diff`, `layout.diff`, `job.status`, `session.ended`, `budget.exceeded`. `version` is monotonically increasing per session or dashboard and is what clients use to dedupe and to resume (`since_version`).

AG-UI runs emit the standard event set; VC messages carry `metadata.speaker = vc_id`; chair decisions and widget diffs are `STATE_DELTA` patches against `{agenda, speaking, widgets, time_range}`.
