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
  reserved: {id: string; x: number; y: number; w: number; h: number}[]; widgets: Widget[] };
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
