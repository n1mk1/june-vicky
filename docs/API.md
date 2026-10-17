# Vicky — REST API contract (as implemented)

Companion to [02-TRD §8](02-TRD.md). Base path `/api/v1` (the web app reaches it through the same-origin proxy `frontend/app/api/v1/[...path]`). Every route needs the access cookie except `GET /healthz` (also at `/healthz`) and `/auth/*`; without it the API returns **401** `{detail}`. JSON everywhere; errors are `{detail: string}`.

Shapes below use TypeScript notation. `Figure` / `MissingFigure` / `Fact` are as in [05-Backend schema §4](05-BACKEND-SCHEMA.md).

## Health and access

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/healthz` | — | `{db: "ok"\|"error", kv: "ok"\|"error"}` |
| POST | `/auth/access` | `{code}` | `{ok: true}` + `Set-Cookie`; 401 wrong code; 429 after 5 tries/min |
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
| GET | `/samples` | — | `{id, name, country, business_model, granularity, one_liner}[]` |
| POST | `/samples/{id}/load` | — | `Engagement` (draft; profile, datasets, proposed mappings and pack facts prefilled) |
| GET | `/engagements` | — | `Engagement[]` (newest first, without `datasets/facts/coverage` detail) |
| GET | `/engagements/active` | — | `Engagement`; 404 when none is confirmed |
| POST | `/engagements` | `{profile: Partial<Profile>}` | `Engagement` (draft) |
| GET | `/engagements/{id}` | — | `Engagement` |
| PUT | `/engagements/{id}/profile` | `Partial<Profile>` | `Engagement` |
| POST | `/uploads` | multipart `file`, `engagement_id` (optional: creates a draft engagement) | `Engagement`; 413 over 10 MB; 415 unsupported type |
| GET | `/datasets/{id}/mapping` | — | `{dataset: DatasetSummary, proposed: ColumnMapping[], confirmed: ColumnMapping[]\|null, targets: {id, label, group}[]}` |
| PUT | `/datasets/{id}/mapping` | `{mapping: ColumnMapping[]}` | same as GET |
| POST | `/engagements/{id}/facts` | `{name, label?, value, unit, period?, kind?}` (founder-typed → `founder_stated`) | `Engagement` |
| DELETE | `/engagements/{id}/facts/{fact_id}` | — | `Engagement` |
| POST | `/engagements/{id}/confirm` | — | `Engagement` (now `active`; any previous active engagement is archived; default dashboard built) |

`ColumnMapping = {source_column, canonical_field: string|null, unit, confidence, note}`.

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
  evaluated: EvaluatedWidget; option: object|null; created_by: "system"|"vicky"|"founder" };
type Dashboard = { id: string; engagement_id: string; version: number; company: string;
  layout: {widget_id: string; x: number; y: number; w: number; h: number}[];
  reserved: {id: string; x: number; y: number; w: number; h: number}[];
  time_range: {last_months?: number; from: string; to: string; label: string} | null; widgets: Widget[] };
type ChatResult = { kind: "widget_added"|"exists"|"missing"|"error"|"time_range"|"question"|"none"; reply: string;
  spec: WidgetSpec|null; widget_id: string|null; missing: MissingFigure|null; time_range: Dashboard["time_range"];
  dashboard: Dashboard|null };
```
`EvaluatedWidget` is `backend/vicky/viz/evaluate.py` (`series[].points[]` each with `{period, label, value, formula, inputs, source}`; `kpi.primary/secondary` with `display`, `formula`, `source`, `missing`). `option` is a complete ECharts option built by code (`viz/echarts.py`); dataset values never come from an LLM.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/dashboards/active` | — | `Dashboard`; 404 with no confirmed engagement |
| GET | `/dashboards/{id}` | `?theme=vicky-dark\|vicky-light` | `Dashboard` |
| POST | `/dashboards/{id}/widgets/preview` | `{spec}` | `{evaluated, option}`; 422 invalid spec/DSL |
| POST | `/dashboards/{id}/widgets` | `{spec, version}` | `Dashboard`; 409 stale version |
| DELETE | `/dashboards/{id}/widgets/{widget_id}` | — | `Dashboard` |
| PATCH | `/dashboards/{id}/layout` | `{layout, version}` | `Dashboard`; 409 stale version |
| PATCH | `/dashboards/{id}/time-range` | `{time_range: {last_months} \| {from, to} (YYYY-MM) \| null, version?}` | `Dashboard` (range resolved against the latest period); 409 stale version; 422 invalid range |
| POST | `/dashboards/{id}/chat` | `{text}` (1–500 chars) | `ChatResult`. Routing: “zoom to …”/“reset zoom” → `kind: time_range`; an explicit chart request (a verb such as show/chart/plot/add, or a grouping such as “by quarter”) → a widget evaluated by code and added as `created_by: vicky` (`widget_added` / `exists`; missing data → `missing` with the reason, nothing added); everything else, including any question about the data and valuation questions, → `kind: answer` from `vicky/qa.py`: `reply` (every number is a computed Figure, checked by the citation audit), `citations[]` (footnotes with formula and source rows), `suggestions[]` (follow-up questions) and `chart` (a request that would chart it). With an API key Claude phrases the answer from the same figures and is held to the same audit; otherwise, or on any failure, the deterministic answer is returned |
| GET | `/realtime/token` | — | `{token}` signed for one hour, for the WebSocket |
| WS | `/ws?token=…&channels=dashboard:{id},session:{id}` | client sends `{type: subscribe\|unsubscribe, channel}`, `{type: ping}` | `{type: hello, versions}` then envelopes `{type, channel, version, ts, payload}`; `widget.diff` (`{version, op, widget_id?, title?, by?}`), `layout.diff`, `time_range.diff` carry the dashboard `version` |

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
| POST | `/areopagus/generate` | body `{description}` (10–2000 chars) → `{persona: VCPersona, source: "claude"\|"heuristic"}`; a draft with `id: "draft"`, not saved. Claude drafts it (Sonnet); without a key, over budget or on failure a keyword heuristic does |
| GET | `/areopagus/{id}` | full `VCPersona` |
| POST | `/areopagus` | create custom (body `VCPersona` without `id`/`builtin`) |
| PUT / DELETE | `/areopagus/{id}` | custom only; built-ins return 403 |
| POST | `/areopagus/{id}/fork` | custom copy of a built-in, keeps its method |

## Preparation court

```ts
type Turn = { seq: number; speaker: string; speaker_name: string; kind: "intro"|"question"|"answer"|"interject"|"coach"|"debrief";
  text: string; lens: string|null; hypothesis_id: string|null; intent: string|null; citations: Citation[]; created_at: string };
type Citation = { marker: number; text: string; figure_id?: string; source_id?: string; label: string; display?: string;
  formula: string; source: object; url?: string };
type Score = { turn_seq: number; accuracy: number|null; dims: {evidence: number; clarity: number; composure: number; investor_fit: number};
  rationale: {good: string; missing: string; correct_figure: Figure|null; strong_answer: string; why_asked: string} };
type Claim = { turn_seq: number; text: string; metric: string; value: number; unit: string; status: ClaimStatus; explanation: string; figure_id: string|null };
type Session = { id: string; status: "live"|"ended"; mode: "prepare"; panel: PersonaSummary[];
  settings: {question_cap: number; coaching: "coached"|"realistic"}; turns: Turn[]; scores: Score[]; claims: Claim[];
  question_count: number; awaiting: "founder"|"panel"|null; next_speaker: string|null; report_id: string|null };
```
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/court/start` | `{panel?: string[] (≤5, default james/alex/mark), question_cap?: 6–20 (default 8), coaching?: "coached"\|"realistic", focus?: string}` | `Session` (Vicky intro + first question); 409 without a confirmed TruthPack |
| GET | `/court/{id}` | — | `Session` |
| POST | `/court/{id}/answer` | `{text}` | `Session` (founder answer, claim checks, score, chair pick, next VC question or coach card; ends at the cap) |
| POST | `/court/{id}/end` | — | `Session` with `report_id` |
| GET | `/sessions` | — | recent sessions `{id, mode, status, started_at, question_count, report_id}[]` |

## Reports

| Method | Path | Returns |
|---|---|---|
| GET | `/reports` | `{id, session_id, created_at, overall, readiness, company}[]` |
| GET | `/reports/{id}` | `Report` (05-Backend schema §4) + `{id, markdown}` |
| GET | `/reports/{id}.md` | `text/markdown` |

## Simulation

| Method | Path | Returns |
|---|---|---|
| POST | `/pitch/start` | 409 `{detail}` without a confirmed TruthPack; otherwise 501 until the voice pipeline lands |

## Notes on shapes (as the frontend uses them)

- **Score scales:** a turn's `accuracy` (session `scores[]`, report `questions[].scores.accuracy`) is the share of the answer's claims that match the data, 0–1. Report `verdict.dims.accuracy` is the same thing averaged and put on the 0–5 scale of the other dimensions so the verdict can average them.
- **Extra fields** returned beyond the tables above: citation `start`, `end`, `kind`; dataset `transposed`, `notes`; mapping `proposer` (`heuristic` | `sample` | `reused`); report list `dims`, `delta`; session `started_at`, `settings.focus`; attack item `quotes` (founder words the item quotes); report question `seq`, `lens`, `vc_name`; report source `label`, `formula`, `as_of`.
- **Profile casing:** `currency` is stored upper-case (`CAD`); figure units are lower-case (`cad`).
- **Uploads:** a file uploaded without an `engagement_id` creates a draft engagement whose profile `granularity` is prefilled from the file (`inferred.granularity`).

## LLM path (Claude minds, column mapper, document facts)

Off by default: with no `ANTHROPIC_API_KEY` (or `LLM_MODE=offline`) every route behaves exactly as above, on the deterministic agents. With a key (`LLM_MODE=auto|live`) the same routes and shapes are served by Claude, and any LLM failure (refusal, timeout, rate limit, invalid output, budget) falls back to the deterministic result for that step. Code in `backend/vicky/llm/`.

| Step | Model / effort | Code keeps the authority |
|---|---|---|
| VC memo (`/court/start`) | `MODEL_DEEP`, high; tool runner over `get_metric` + the persona's kit tools | starts from code's gap ownership; a hypothesis must name an attack item or a real figure id; confidences clamped; opening question audited |
| Belief update + bid (`/court/{id}/answer`) | `MODEL_FAST`, low; one call per VC, in parallel | no-concession rule (confidence drops only on a cited matching figure), at most ±0.35 per answer; bids/targets validated |
| Chair | `MODEL_FAST`, low, no thinking | must name a ranked candidate within `CHAIR_TIMEOUT_S` (1.5 s), else `ranked[0]`; logged in `chair_decisions` with `fallback` |
| VC line | `MODEL_FAST`, medium | `audit_text`; on failure regenerated once with the findings, then the offline line (`turn.audit.regenerated`) |
| Judge | `MODEL_DEEP`, high | dims 2–5 clamped to 0–5; accuracy, correct figure and why-asked stay code's; rationale and strong answer audited |
| Claim extraction | `MODEL_TINY`, low | merged with code's extraction; a claim must quote the answer verbatim, number included |
| Column mapper (`POST /uploads`, series tables) | `MODEL_FAST`, medium, ≤ 30 s | targets validated, units set by code, merged with the heuristic; a heuristic total column keeps its field |
| Document facts (FR-7) | `MODEL_DEEP`, medium, two passes | see below |

Opus/Sonnet calls opt into server-side fallbacks (`fallbacks: "default"`, `LLM_SERVER_FALLBACKS`). Every response's usage is priced at list rates into `vicky:spend:{date}`.

**Budget.** Once the day's spend reaches `DAILY_USD_BUDGET`, `POST /court/start` and `POST /court/{id}/answer` return **402** `{detail: "Daily budget reached. …"}`; everything else keeps working. Never 402 on the offline path.

**Uploads of PDF / DOCX / MD (FR-7).** With a key, `POST /uploads` also enqueues an `extract` job. Pass 1 sends the document with citations enabled (PDF through the Files API, DOCX/MD as text) and asks for one fact per line; pass 2 (`messages.parse`) turns the cited lines into facts. A fact lands only if its number appears in its cited text; the page (or char span) comes from the citation object, and pypdf checks the cited text is on that page. Facts land in the TruthPack as `pending` for the confirm step:

```ts
type DocFact = Fact & { status: "pending"; kind: "historical"|"forecast";   // forecast names are prefixed "plan."
  source: { kind: "pdf"|"docx"|"md"; ref: string /* "update.pdf, p. 2" */; page: number|null;
            cited_text: string; verified: boolean };
  note: string|null };                                                     // "Check this: cited text not found on page 1."
```

`Engagement` gains `extract_jobs: {id, upload_id, status: "queued"|"running"|"done"|"failed"|"stale", error, result: {added, flagged, dropped, lines}|null}[]` (newest first; empty on the offline path). The upload's `status` goes `stored → extracted` (or `failed`). `job.status` events are published on `engagement:{id}`.

| Method | Path | Returns |
|---|---|---|
| GET | `/jobs/{id}` | `{id, kind, status, error, result, enqueued_at, finished_at}` |
| POST | `/jobs/{id}/retry` | `{ok: true}` (re-runs a failed or stale job) |

Mapping `proposer` gains `"claude"` (Claude's proposal merged with the heuristic). Memos stored for a session carry `source: "llm"` when Claude wrote them.
