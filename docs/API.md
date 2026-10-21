# Vik — REST API contract (as implemented)

Companion to [02-TRD §8](02-TRD.md). Base path `/api/v1` (the web app reaches it through the same-origin proxy `frontend/app/api/v1/[...path]`). Every route needs the access cookie except `GET /healthz` (also at `/healthz`) and `/auth/*`; without it the API returns **401** `{detail}`. JSON everywhere; errors are `{detail: string}`. A request body over `REQUEST_MAX_BYTES` is **413** before it is read; `NaN`/`Infinity` in a numeric field is **422**.

Shapes below use TypeScript notation. `Figure` / `MissingFigure` / `Fact` are as in [05-Backend schema §4](05-BACKEND-SCHEMA.md).

## Health and access

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/healthz` | — | 200 `{db: "ok", kv: "ok"\|"error"}`; **503** with the same body when `db` is `"error"` (`kv` is informational) |
| POST | `/auth/access` | `{code}` | `{ok: true}` + `Set-Cookie`; 401 wrong code; 429 after 5 tries/min per IP, or for everyone after `ACCESS_FAILURES_PER_MIN` (60) wrong codes/min across all IPs |
| GET | `/auth/session` | — | `{ok: boolean}` |
| POST | `/auth/logout` | — | `{ok: true}` |

## Engagements and the TruthPack flow

```ts
type Profile = { name: string; country: string; currency: string; fiscal_year_start_month: number;
  stage: "pre_seed"|"seed"|"series_a"|"series_b_plus"|"other"; round_type: string|null; round_size: number|null;
  business_model: "recurring"|"other"; granularity: "month"|"quarter"; one_liner?: string };
type DatasetSummary = { id: string; upload_id: string|null; name: string; table_kind: string; granularity: string;
  period_axis: string|null; columns: {name: string; dtype: string; sample_values: unknown[]; null_rate: number}[];
  mapping_confirmed: boolean; mapped: number; total: number };
type Engagement = { id: string; name: string; status: "draft"|"active"|"archived"; created_at: string;
  confirmed_at: string|null; profile: Profile|null;
  uploads: {id: string; filename: string; kind: string; status: string; size: number}[];
  datasets: DatasetSummary[]; facts: Fact[];
  truthpack: {id: string; version: number; confirmed_at: string|null}|null;
  coverage: CoverageItem[] };   // preview computed from the current (possibly unconfirmed) mapping
type CoverageItem = { group: string; metric_id: string; label: string; available: boolean; needs: string[]; reason?: string };
```

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/engagements` | — | `Engagement[]` (newest first, without `datasets/facts/coverage` detail) |
| GET | `/engagements/active` | — | `Engagement`; 404 when none is confirmed |
| POST | `/engagements` | `{profile: Partial<Profile>}` | `Engagement` (draft) |
| GET | `/engagements/{id}` | — | `Engagement` |
| PUT | `/engagements/{id}/profile` | `Partial<Profile>` | `Engagement` |
| POST | `/uploads` | multipart `file`, `engagement_id` (optional: creates a draft engagement) | `Engagement`; 413 over 10 MB; 415 unsupported type |
| GET | `/datasets/{id}/mapping` | — | `{dataset: DatasetSummary, proposed: ColumnMapping[], confirmed: ColumnMapping[]\|null, targets: {id, label, group, kind}[]}` (`kind`: money · count · date · text · custom; `custom` targets are the engagement's own custom fields) |
| PUT | `/datasets/{id}/mapping` | `{mapping: ColumnMapping[]}` | same as GET. One date axis per table (422 otherwise); a new axis column re-reads the table from its upload (422 when that column doesn't read as dates). The unit follows the field: `date` for the axis, a currency for money, a count unit for counts. A **custom field**: `canonical_field: "custom."` with `label` ("Active pilots") creates `custom.active_pilots`; an existing `custom.<slug>` reuses it (422 for an id that isn't `custom.` + lowercase letters, digits, `_`). Custom columns are labelled series for charts, chat and search, not inputs to standard metrics |
| POST | `/engagements/{id}/facts` | `{name, label?, value, unit, period?, kind?}` (founder-typed → `founder_stated`) | `Engagement` |
| DELETE | `/engagements/{id}/facts/{fact_id}` | — | `Engagement` |
| POST | `/engagements/{id}/confirm` | — | **Confirm knowledge base.** `Engagement` (now `active`; any previous active engagement is archived; default dashboard built) plus `index: {build_id, status}`: the confirmed profile, mappings and facts are written to `company/Confirmed knowledge base.md` and the search index is rebuilt from the whole vault. Unreviewed low-confidence column guesses are kept as raw columns (with a dataset note) instead of blocking the confirm |

`ColumnMapping = {source_column, canonical_field: string|null, unit, confidence, note}`; `unit` is a figure unit (a currency, `pct`, `count`, `months`, `ratio`, `x`), `date` or `text`. Dataset columns carry `unit_hint` (`pct` · `date` · `text`) and `scale` (1000 when the header or a title row says the values are in thousands).

## Figures (active engagement unless `?engagement_id=`)

| Method | Path | Returns |
|---|---|---|
| GET | `/truth` | `{engagement_id, truthpack_id, version, confirmed_at, company, profile, figures: (Figure\|MissingFigure)[], coverage: CoverageItem[], attack_list: AttackItem[], facts: Fact[]}` |
| GET | `/metrics` | `(Figure\|MissingFigure)[]` |
| GET | `/metrics/{id}` | `Figure\|MissingFigure`; 404 unknown |
| GET | `/attack-list?lens=` | `AttackItem[]` = `{id, lens, topic, detail, severity, figure_ids, source_id, missing}` |
| GET | `/coverage` | `CoverageItem[]` |
| POST | `/claims/check` | body `{metric, value, unit, period?, is_forecast?}` → `ClaimCheck` = `{status, metric, value, unit, figure, figure_id, delta, explanation}` |
| GET | `/glossary?term=` | `{term, aliases, text, source_id}[]` |
| GET | `/sources?topic=` | source entries |

## Dashboards

```ts
type Widget = { id: string; role: string; spec: WidgetSpec; status: "ok"|"missing"|"error";
  evaluated: EvaluatedWidget; option: object|null; created_by: "system"|"vik"|"founder" };
type Dashboard = { id: string; engagement_id: string; version: number; company: string;
  layout: {widget_id: string; x: number; y: number; w: number; h: number}[];
  reserved: {id: string; x: number; y: number; w: number; h: number}[];
  time_range: {last_months?: number; from: string; to: string; label: string} | null; widgets: Widget[] };
type ChatResult = { kind: "widget_added"|"exists"|"missing"|"error"|"time_range"|"question"|"none"; reply: string;
  spec: WidgetSpec|null; widget_id: string|null; missing: MissingFigure|null; time_range: Dashboard["time_range"];
  dashboard: Dashboard|null };
```
`EvaluatedWidget` is `backend/vik/viz/evaluate.py` (`series[].points[]` each with `{period, label, value, formula, inputs, source}`; `kpi.primary/secondary` with `display`, `formula`, `source`, `missing`). `option` is a complete ECharts option built by code (`viz/echarts.py`); dataset values never come from an LLM.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/dashboards/active` | — | `Dashboard`; 404 with no confirmed engagement |
| GET | `/dashboards/{id}` | `?theme=vik-dark\|vik-light` | `Dashboard` |
| POST | `/dashboards/{id}/widgets/preview` | `{spec}` | `{evaluated, option}`; 422 invalid spec/DSL |
| POST | `/dashboards/{id}/widgets` | `{spec, version}` | `Dashboard`; 409 stale version |
| DELETE | `/dashboards/{id}/widgets/{widget_id}` | — | `Dashboard` |
| PATCH | `/dashboards/{id}/layout` | `{layout, version}` | `Dashboard`; 409 stale version |
| PATCH | `/dashboards/{id}/time-range` | `{time_range: {last_months} \| {from, to} (YYYY-MM) \| null, version?}` | `Dashboard` (range resolved against the latest period); 409 stale version; 422 invalid range |
| POST | `/dashboards/{id}/chat` | `{text}` (1–500 chars) | `ChatResult`. Routing: “zoom to …”/“reset zoom” → `kind: time_range`; an explicit chart request (a verb such as show/chart/plot/add, or a grouping such as “by quarter”) → a widget evaluated by code and added as `created_by: vik` (`widget_added` / `exists`; missing data → `missing` with the reason, nothing added); everything else, including any question about the data and valuation questions, → `kind: answer` from `vik/qa.py`: `reply` (every number is a computed Figure, checked by the citation audit), `citations[]` (footnotes with formula and source rows), `suggestions[]` (follow-up questions) and `chart` (a request that would chart it). With an API key Gemini phrases the answer from the same figures and is held to the same audit; otherwise, or on any failure, the deterministic answer is returned. When the knowledge base has notes, Gemini can also call `kb_search` / `kb_read` and quote notes; offline, a question the data can't answer is looked up in the notes by keyword (`topic: notes`). A note is quoted word for word and followed by `[kb:path]`; its citation has `kind: "note"`, `display` = the path and `source: {kind: "note", ref: path, note_id}`. Numbers outside such a quote still need a Figure ([07 §Agents](07-KNOWLEDGE-BASE.md#agents-read-the-vault)). Once confirming the knowledge base has built the search index, notes come from hybrid retrieval and every model-written sentence must cite a figure or quote a note; a figure's citation names its note in `source.kb_note: {id, path}`. When the notes are needed but not found, the answer carries `offer: {kind: "catch_all", id, prompt, notes, expires_at}` and nothing more runs until the user answers it ([08-RAG.md §Ask Vik](08-RAG.md#ask-vik)) |
| POST | `/dashboards/{id}/chat/catch-all` | `{offer_id, accept: boolean}` | The user's answer to a catch-all offer. `accept: true` runs Gemini 3.5 Flash-Lite (route `qa_full`) over the whole vault once and returns a `ChatResult` answer (audited, cached); `accept: false` runs nothing (**204**). An expired (15 min), used or other dashboard's offer is **410** |
| GET | `/realtime/token` | — | `{token}` signed for one hour, for the WebSocket |
| WS | `/ws?token=…&channels=dashboard:{id},session:{id},kb` | client sends `{type: subscribe\|unsubscribe, channel}`, `{type: ping}` | `{type: hello, versions}` then envelopes `{type, channel, version, ts, payload}`; `widget.diff` (`{version, op, widget_id?, title?, by?}`), `layout.diff`, `time_range.diff` carry the dashboard `version`; `job.status` (`{job_id, kind, status, error?}`) goes out on the job's `session:{id}`, else its `engagement:{id}`, else `kb`; `kb.index.ready` (`{build_id, chunks}`) and `kb.index.failed` (`{build_id, error}`) on `kb` |

The browser connects to the API's public URL (`API_PUBLIC_WS_URL`, served by the web app at `/api/realtime`), because the web proxy does not carry sockets. Clients drop envelopes at or below the last `version` seen per channel and re-fetch REST state after every reconnect.

## The Areopagus (investor personas)

```ts
type PersonaSummary = { id: string; name: string; firm: string; archetype: string; glyph: string; bio: string;
  lens: string; signature_move: string; priorities: Record<string, number>; style: {...}; kits: string[];
  builtin: boolean; base_archetype: string|null; version: number };
```
| Method | Path | Returns |
|---|---|---|
| GET | `/areopagus` | `PersonaSummary[]` (built-ins first) |
| GET | `/areopagus/templates` | builder templates |
| GET | `/areopagus/options` | `{lenses: [{id, label}], glyphs, cheque_roles}` for the builder form |
| POST | `/areopagus/generate` | body `{description}` (10–2000 chars) → `{persona: VCPersona, source: "gemini"\|"heuristic"}`; a draft with `id: "draft"`, not saved. Gemini drafts it (`MODEL_FAST`, route `persona`); without a key, over budget or on failure a keyword heuristic does |
| GET | `/areopagus/{id}` | full `VCPersona` |
| POST | `/areopagus` | create custom (body `VCPersona` without `id`/`builtin`) |
| PUT / DELETE | `/areopagus/{id}` | custom only; built-ins return 403 |
| POST | `/areopagus/{id}/fork` | custom copy of a built-in, keeps its method |

## Court (the Simulation's Q&A)

There is no route that starts a court on its own: `POST /pitch/{id}/end` in after mode opens one (see [Simulation](#simulation)), with the pitch's panel, 6 questions, coached mode and knowledge checks off, and the browser runs it on the routes below.

```ts
type Turn = { seq: number; speaker: string; speaker_name: string; kind: "intro"|"question"|"answer"|"interject"|"coach"|"debrief";
  text: string; lens: string|null; hypothesis_id: string|null; intent: string|null; citations: Citation[];
  review: {verdict: "approve"|"revise"; issues: string[]; note: string; source: string; revised: boolean; final?: string}|null;  // Vik's review of the drafted line
  created_at: string };
type Citation = { marker: number; text: string; figure_id?: string; source_id?: string; label: string; display?: string;
  formula: string; source: object; url?: string };
type Score = { turn_seq: number; accuracy: number|null; dims: {evidence: number; clarity: number; composure: number; investor_fit: number};
  rationale: {good: string; missing: string; correct_figure: Figure|null; strong_answer: string; why_asked: string} };
type Claim = { turn_seq: number; text: string; metric: string; value: number; unit: string; status: ClaimStatus; explanation: string; figure_id: string|null };
type Session = { id: string; status: "live"|"ended"; mode: "simulate"; panel: PersonaSummary[];
  settings: {question_cap: number; coaching: "coached"|"realistic"; focus: string|null; knowledge: boolean};
  turns: Turn[]; scores: Score[]; claims: Claim[];
  knowledge: {turn_seq, question_seq, vc_id, lens, verdict, label, explanation, citations, expected, retrieval}[];
  knowledge_ready: {on: boolean; probes: number; left: number};
  question_count: number; awaiting: "founder"|"panel"|null; next_speaker: string|null; report_id: string|null };
```
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/court/{id}` | — | `Session` |
| POST | `/court/{id}/answer` | `{text}` (1–4000 chars) | `Session` (founder answer, claim checks, score, chair pick, next VC question or coach card; ends at the cap); 409 once the session has ended |
| POST | `/court/{id}/end` | — | `Session` with `report_id` |
| GET | `/sessions` | — | recent sessions `{id, mode, status, started_at, question_count, report_id}[]` (sessions recorded by the retired text court keep `mode: "prepare"`) |

## Reports

| Method | Path | Returns |
|---|---|---|
| GET | `/reports` | `{id, session_id, created_at, overall, readiness, company}[]` |
| GET | `/reports/{id}` | `Report` (05-Backend schema §4) + `{id, markdown}` |
| GET | `/reports/{id}.md` | `text/markdown` |

## Simulation

| Method | Path | Returns |
|---|---|---|
| POST | `/pitch/start` | No body: 409 `{detail}` without a confirmed TruthPack; otherwise `{voice: bool, stt: {url, model_id, sample_rate}}` (`voice` false without `ELEVENLABS_API_KEY`). Body `{mode: live\|after, panel[], deck_id?}`: also opens a pitch → `pitch` (status `presenting`, Vik's opening in `say[]`, `voices` {speaker → ElevenLabs voice id}: one distinct voice per seat and Vik, cast for each archetype) |
| POST | `/pitch/deck` | Multipart PDF or PowerPoint (≤ 40 slides): `{id, filename, kind: pdf\|pptx, slides[{n, text, image (JPEG data URL; null for a PowerPoint), title, bullets[], claims[], kb[]}]}`; each slide's figures checked by code (they replace the TruthPack's deck claims) and its statements against the knowledge base (`kb[]`: `{id, slide, source, text, topic, verdict: supported\|contradicted\|new\|unclear, quote, path, cite, why}`). The deck is never added to the knowledge base. 415 for anything but a PDF or a zip-based Office file, 422 for one that isn't a deck |
| GET | `/pitch/{id}` | The pitch: `mode, status, panel, ledger[], interrupts[], pending, court_id, stats` (Redis, 6 h) |
| POST | `/pitch/{id}/segment` | `{text, slide?, t_ms}`, a transcript segment: `{claims[], kb[], interrupt?, pitch}` (`kb[]`: its statements checked against the knowledge base, as on `/pitch/deck`; `pitch.kb` has them all). Live mode: a contradiction of the data or of the notes (or a forecast as fact) may bring `interrupt {speaker, text, on: data\|notes}`, scored in code; ≤ 1 per slide, 30 s cooldown. 409 once the presentation is over |
| POST | `/pitch/{id}/reply` | `{text}`, the answer to the open interrupt: judged → `{say[], score, pitch}` (the investor hands the floor back). 409 when nobody asked |
| POST | `/pitch/{id}/end` | Live: `{pitch (status ended, stats, Vik's wrap-up in say[]), court: null}`. After: spoken claims join the deck claims, then `court` is a new court session (`mode: simulate`, 6 questions, coached, knowledge checks off; up to four statements the notes contradict or don't cover become doubts) run on `/court/*` |
| POST | `/voice/stt-token` | `{token, url, model_id, sample_rate}`: a single-use ElevenLabs realtime Scribe token (15 min). 503 without a key, 502/503 when ElevenLabs refuses |
| GET | `/voice/tts?text=&speaker=&voice_id=` | `audio/mpeg`, streamed. `text` ≤ 1200 chars; `voice_id` wins, else `speaker`'s voice (persona id → its `voice_id`, else its archetype's; `vik` or none → `VIK_VOICE_ID`), else a premade voice. The pitch room passes `voice_id` from `pitch.voices`. Model `ELEVENLABS_TTS_MODEL` (default `eleven_flash_v2_5`) |

## Knowledge base

Design: [07-KNOWLEDGE-BASE.md](07-KNOWLEDGE-BASE.md). One global vault.

```ts
type KbNote = { id: string; path: string; folder: string; title: string; kind: "table"|"document"|"note"|"hub";
  format: "md"|"csv"; tags: string[]; summary: string; links: string[];   // related-note paths
  meta: {source?: string; pages?: number; ocr_pages?: number[]; rows?: number; columns?: string[]; slides?: number; charts?: number};
  author: "import"|"ai"|"founder"; file_id: string|null; size: number; version: number;
  organized_at: string|null; created_at: string; updated_at: string };
type KbLinkRef = { id: string|null; path: string|null; title: string };   // id null: linked but not written
```

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/kb/status` | — | `{notes, hubs, tables, documents, unorganized, organized_at, files, failed, bytes, jobs: Job[], running, failures: {id, filename, error}[], ocr: boolean, llm: boolean, llm_health: {ok: boolean\|null, error: string\|null, at: number\|null}, index: {status: "none"\|"building"\|"ready"\|"failed", build_id, built_at, notes, chunks, vectors, changed_since, latest}, rag: {…counters, offer_rate, accept_rate}}`; `index` is the search index that confirming the knowledge base builds ([08-RAG.md](08-RAG.md)); `changed_since` counts notes edited or added after it; `llm_health` is this process's last live Gemini call (`ok: false`: agents are running offline; `error` says why, e.g. `credentials rejected` for an invalid key or `rate limited` while a model rests after a 429) |
| POST | `/kb/index` | — | `{build_id, status: "queued"}`: rebuild the search index from the vault as it is now (Retry after a failed build); **422** when the vault is empty |
| GET | `/kb/notes` | — | `KbNote[]` (no content) |
| GET | `/kb/notes/{id}` | — | `KbNote & {content, backlinks: KbLinkRef[], outlinks: KbLinkRef[], file?: {id, filename, kind, size, status}}` |
| POST | `/kb/notes` | `{title, content?, path?, format?: "md"\|"csv", tags?, summary?, links?}` | the note (author `founder`) |
| PUT | `/kb/notes/{id}` | any of `{content, title, path, tags, summary, links, version}` | the note; **409** when `version` is stale; a new `path` is made unique and related links follow it |
| DELETE | `/kb/notes/{id}` | — | `{ok: true}`; the original goes too once no note uses it |
| GET | `/kb/graph` | — | `{nodes: {id, title, path, kind, folder, tags, author, degree}[], links: {source, target, type: "link"\|"related"}[]}`; unresolved wikilinks are nodes with `kind: "missing"`, `id: "missing:<target>"` |
| GET | `/kb/search?q=&limit=` | — | `(KbNote & {snippet})[]`, full text over title, summary and content |
| POST | `/kb/import` | multipart `files` (≤ 200 per request, each ≤ `KB_UPLOAD_MAX_BYTES`, **413** over) | `{job_id: string\|null, files: {filename, status: "stored"\|"duplicate"\|"failed", error?, id?}[]}`; the `kb_ingest` job converts and organizes |
| POST | `/kb/organize` | `{full?: boolean}` | `{job_id}`; `full` re-organizes every note, otherwise only new ones |
| GET | `/kb/export?originals=` | — | `application/zip`: the vault (`.md` with frontmatter, `.csv`, `.vik/meta.json`), plus `_originals/` when asked |
| GET | `/kb/files/{id}` | — | the original file as uploaded |
| POST | `/kb/autofill` | — | `{engagement: Engagement, by: "gemini"\|"heuristic", profile: {field, value, evidence}[], added: {note, as}[], skipped: {note, reason}[], index: KbIndexStatus}`; a new **draft** engagement for the intake flow. The search index is not rebuilt here: confirming the knowledge base does it ([08-RAG.md §Indexing](08-RAG.md#indexing)); **422** when the vault is empty |

Imports, organize passes and index builds report on the `kb` WebSocket channel (`job.status`, then `kb.index.ready` or `kb.index.failed` for a build). The Knowledge base view reloads the vault and the search status on those events, including for jobs another tab started; `GET /kb/status` stays the record, polled only as a fallback.

`Engagement` also carries `profile_sources: Record<field, string>`: where each autofilled profile value came from (`From [[path]]: “quote”`).

## Notes on shapes (as the frontend uses them)

- **Score scales:** a turn's `accuracy` (session `scores[]`, report `questions[].scores.accuracy`) is the share of the answer's claims that match the data, 0–1. Report `verdict.dims.accuracy` is the same thing averaged and put on the 0–5 scale of the other dimensions so the verdict can average them.
- **Extra fields** returned beyond the tables above: citation `start`, `end`, `kind`; dataset `transposed`, `notes`; mapping `proposer` (`heuristic` | `sample` | `reused`); report list `dims`, `delta`; session `started_at`, `settings.focus`; attack item `quotes` (founder words the item quotes); report question `seq`, `lens`, `vc_name`; report action plan `{priority, text, lens}`; report source `label`, `formula`, `as_of`.
- **Profile casing:** `currency` is stored upper-case (`CAD`); figure units are lower-case (`cad`).
- **Uploads:** a file uploaded without an `engagement_id` creates a draft engagement whose profile `granularity` is prefilled from the file (`inferred.granularity`).

## LLM path (Gemini minds, column mapper, document facts)

Off by default: with no `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), or with `LLM_MODE=offline`, every route behaves exactly as above, on the deterministic agents. With a key (`LLM_MODE=auto|live`) the same routes and shapes are served by Google Gemini, and any LLM failure (refusal, timeout, rate limit, rejected key, invalid output, budget) falls back to the deterministic result for that step. The key's tier is `GEMINI_TIER`: `free` (the default, a free AI Studio key) or `paid`; the models below are the free-tier defaults. Code in `backend/vik/llm/` ([02-TRD §5](02-TRD.md#5-agents)).

| Step | Model / thinking | Code keeps the authority |
|---|---|---|
| VC memo (court opening, `POST /pitch/{id}/end` in after mode) | `MODEL_INVESTOR` (Gemini 3.6 Flash), low; tool loop over `get_metric`, the persona's kit tools and, with notes in the vault, `kb_search` / `kb_read` | starts from code's gap ownership; a hypothesis must name an attack item or a real figure id; confidences clamped; opening question audited |
| Belief update + bid (`/court/{id}/answer`) | `MODEL_INVESTOR`, low; one call per VC, in parallel | no-concession rule (confidence drops only on a cited matching figure), at most ±0.35 per answer; bids/targets validated |
| Chair (Vik) | `MODEL_VIK` (Gemini 3.8 Flash; Gemini 4 Argon on a paid key), low | must name a ranked candidate within `CHAIR_TIMEOUT_S` (6 s), else `ranked[0]`; logged in `chair_decisions` with `fallback` |
| VC line | `MODEL_INVESTOR`, low | `audit_text`; on failure regenerated once with the findings, then the offline line (`turn.audit.regenerated`) |
| Line review (Vik) | `MODEL_VIK`, low | code's checks (one question, under 70 words, not a repeat, not giving a knowledge answer away) always count; a line sent back is rewritten once and kept only if it passes them (`turn.review`) |
| Judge (Vik) | `MODEL_VIK`, low | dims 2–5 clamped to 0–5; accuracy, correct figure and why-asked stay code's; rationale and strong answer audited |
| Claim extraction | `MODEL_TINY` (Gemini 3.5 Flash-Lite), low | merged with code's extraction; a claim must quote the answer verbatim, number included |
| Column mapper (`POST /uploads`, series tables) | `MODEL_FAST` (Gemini 3.8 Flash), medium, ≤ 30 s | targets validated, units set by code, merged with the heuristic; a heuristic total column keeps its field |
| Document facts (FR-7) | `MODEL_DEEP` (Gemini 3.8 Flash; Gemini 4 Argon on a paid key), medium; one call per part | see below |

The effort is Gemini's `thinking_level`. Structured outputs use `response_json_schema` and are validated with Pydantic. There are no server-side fallbacks and no explicit prompt-cache breakpoints (Gemini caches repeated prefixes implicitly; cached tokens are billed at the cached rate). On a paid key (`GEMINI_TIER=paid`), every response's `usage_metadata` is priced at list rates into `vik:spend:{date}` (and the Postgres `spend` table), and each call reserves its estimated cost on the same counter while it is in flight; on the free tier calls are priced at $0 and nothing is reserved.

**Rate limits.** On the free tier each model gets at most `GEMINI_RPM` requests a minute (default 10) from each process; a call waits for a slot, and a step with a timeout that runs out first takes its deterministic result. On any tier, when Gemini answers 429 that model rests for the error's `retryDelay` (else `GEMINI_COOLDOWN_S`, 60 s): its calls take the deterministic result at once, without a request, and other models are unaffected.

**Budget (`GEMINI_TIER=paid` only).** Once the day's spend reaches `DAILY_USD_BUDGET`, `POST /court/{id}/answer`, `POST /pitch/deck`, `POST /pitch/{id}/segment`, `POST /pitch/{id}/reply` and `POST /pitch/{id}/end` return **402** `{detail: "Daily budget reached. …"}`; everything else keeps working (LLM steps elsewhere use their deterministic result). Never 402 on the offline path, nor on a free-tier key, whose limits are requests, not dollars.

**Uploads of PDF / DOCX / MD (FR-7).** With a key, `POST /uploads` also enqueues an `extract` job for a PDF, DOCX or markdown file, and for a CSV/XLSX table with no date axis (a KPI sheet, a cap table). One structured call per part returns the facts, each with the passage that states it copied word for word (`cited_text`) and, for a PDF, its page. A PDF is sent as the file itself (inline up to 15 MB, otherwise through the Gemini Files API, deleted after the call); DOCX, markdown and tables are sent as text. Long documents are read in parts (15 PDF pages, about 60,000 text characters), in parallel; a part whose answer overflows or fails validation is halved and read again, down to one page or a short chunk. Then code decides: a fact whose number isn't in its quote, or labelled a deck, slide or pitch claim, is dropped; code locates each quote itself (the model's page first, then every page via pypdf; the char span in text), so the page is code's; a quote it can't find is kept but flagged (`verified: false` plus a note). Facts land in the TruthPack as `pending` for the confirm step:

```ts
type DocFact = Fact & { status: "pending"; kind: "historical"|"forecast";   // forecast names are prefixed "plan."
  source: { kind: "pdf"|"docx"|"md"|"csv"|"xlsx"; ref: string /* "update.pdf, p. 2" */; page: number|null;
            cited_text: string; verified: boolean };
  note: string|null };                                                     // "Check this: cited text not found on page 1."
```

`Engagement` gains `extract_jobs: {id, upload_id, status: "queued"|"running"|"done"|"failed"|"stale", error, result: {added, flagged, dropped, lines}|null}[]` (newest first; empty on the offline path). The upload's `status` goes `stored → extracted` (or `failed`). `job.status` events are published on `engagement:{id}`.

| Method | Path | Returns |
|---|---|---|
| GET | `/jobs/{id}` | `{id, kind, status, error, result, enqueued_at, finished_at}`; 404 unknown id |
| POST | `/jobs/{id}/retry` | `{ok: true}`: re-queues a `failed` or `stale` job; **404** unknown or malformed id; **409** when the job is `queued`, `running` or `done` |

A job cancelled mid-run (worker `job_timeout`, redeploy, instance sleep) ends `failed` with `error: "interrupted"`. The sweeper marks `stale` a job `queued` for over 15 min or `running` for over 15 min (job timeout 600 s + 5 min margin).

Mapping `proposer` gains `"gemini"` (Gemini's proposal merged with the heuristic). Memos stored for a session carry `source: "llm"` when Gemini wrote them.
