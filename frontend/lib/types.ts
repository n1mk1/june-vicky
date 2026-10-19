/**
 * Shapes returned by the Vik API (docs/API.md, docs/05-BACKEND-SCHEMA.md §4).
 * Every number in these objects is computed by the backend's metrics engine; the frontend only formats it.
 */

// ---------------------------------------------------------------- figures and sources

export type Unit = "cad" | "usd" | "gbp" | "eur" | "aud" | "pct" | "months" | "count" | "ratio" | "x" | (string & {});
export type FigureKind = "historical" | "forecast" | "founder_claim" | "benchmark";

export interface Source {
  kind: string;
  ref?: string;
  dataset_id?: string | null;
  page?: number | null;
  cited_text?: string | null;
  verified?: boolean | null;
  url?: string | null;
  source_id?: string | null;
}

export interface Figure {
  id: string;
  label: string;
  value: number;
  unit: Unit;
  formula: string;
  inputs?: { figure_id?: string | null; dataset_id?: string | null; column?: string | null; period?: string | null; value?: number | null }[];
  source: Source;
  kind: FigureKind;
  period?: string | null;
  group?: string;
  display: string;
  missing?: false;
}

export interface MissingFigure {
  id: string;
  label?: string;
  needs: string[];
  reason: string;
  group?: string;
  missing: true;
}

export type AnyFigure = Figure | MissingFigure;

export const isMissing = (f: AnyFigure | null | undefined): f is MissingFigure => !!f && (f as MissingFigure).missing === true;

export interface Fact {
  id: string;
  name: string;
  label?: string;
  value: number;
  unit: string;
  period?: string | null;
  kind: FigureKind;
  source: Source;
  status?: "pending" | "confirmed" | "removed";
  target_metric?: boolean;
  note?: string | null;
}

// ---------------------------------------------------------------- engagements

export type Stage = "pre_seed" | "seed" | "series_a" | "series_b_plus" | "other";

export interface Profile {
  name: string;
  country: string;
  currency: string;
  fiscal_year_start_month: number;
  stage: Stage;
  round_type: string | null;
  round_size: number | null;
  business_model: "recurring" | "other";
  granularity: "month" | "quarter";
  one_liner?: string;
}

export interface DatasetColumn {
  name: string;
  dtype: string;
  sample_values: unknown[];
  null_rate: number;
  /** The currency the column's header or cells name, read from the file. */
  currency?: string | null;
  /** What the values are when the file shows it: "pct", "date" or "text". */
  unit_hint?: string | null;
  /** The values were multiplied by this because the header or title said "$000" or "in millions". */
  scale?: number;
}

export interface DatasetSummary {
  id: string;
  upload_id: string | null;
  name: string;
  table_kind: string;
  granularity: string;
  period_axis: string | null;
  columns: DatasetColumn[];
  mapping_confirmed: boolean;
  mapped: number;
  total: number;
  transposed?: boolean;
  notes?: string[];
}

export interface CoverageItem {
  group: string;
  metric_id: string;
  label: string;
  available: boolean;
  needs: string[];
  reason?: string;
  kind?: string;
  source_kind?: string;
}

export interface Upload {
  id: string;
  filename: string;
  kind: string;
  status: string;
  size: number;
}

export interface Engagement {
  id: string;
  name: string;
  status: "draft" | "active" | "archived";
  created_at: string;
  confirmed_at: string | null;
  profile: Profile | null;
  /** Where each profile value came from when it was filled in for the founder (e.g. from the knowledge base). */
  profile_sources?: Record<string, string>;
  uploads: Upload[];
  datasets: DatasetSummary[];
  facts: Fact[];
  truthpack: { id: string; version: number; confirmed_at: string | null } | null;
  coverage: CoverageItem[];
  /** What building the model left out or reinterpreted (short quarters, missing exchange rates), from the metrics engine. */
  model_notes?: string[];
  /** Reading facts out of documents (and tables with no dates); each lands in step 03 when its job is done. */
  extract_jobs?: { id: string; upload_id: string; status: string; error: string | null }[];
}

export interface ColumnMapping {
  source_column: string;
  canonical_field: string | null;
  unit: string;
  confidence: number;
  note: string;
  /** A custom field's name as the founder typed it (`canonical_field` is `custom.<slug>`). */
  label?: string;
}

export interface MappingTarget {
  id: string;
  label: string;
  group: string;
  /** What a column mapped to it holds, which sets the column's unit. */
  kind?: "money" | "count" | "date" | "text" | "custom";
}

export interface MappingResponse {
  dataset: DatasetSummary;
  proposed: ColumnMapping[];
  confirmed: ColumnMapping[] | null;
  targets: MappingTarget[];
}

// ---------------------------------------------------------------- truth

export interface AttackItem {
  id: string;
  lens: string;
  topic: string;
  detail: string;
  severity: number;
  figure_ids: string[];
  source_id: string | null;
  missing: boolean;
}

export interface Truth {
  engagement_id: string;
  truthpack_id: string;
  version: number;
  confirmed_at: string | null;
  company: string;
  profile: Profile;
  figures: AnyFigure[];
  coverage: CoverageItem[];
  /** What building the model left out or reinterpreted (short quarters, missing exchange rates), from the metrics engine. */
  model_notes?: string[];
  attack_list: AttackItem[];
  facts: Fact[];
}

// ---------------------------------------------------------------- dashboards

export interface InputRef {
  field?: string | null;
  figure_id?: string | null;
  raw?: string | null;
  period?: string | null;
  value?: number | null;
  dataset_id?: string | null;
  ref?: string | null;
}

export interface PointSource {
  kind: string;
  ref?: string;
  dataset_id?: string | null;
}

export interface Point {
  period: string;
  label: string;
  value: number | null;
  formula: string;
  inputs: InputRef[];
  source: PointSource | null;
}

export interface EvaluatedSeries {
  label: string;
  ref: string;
  unit: string | null;
  axis: "left" | "right";
  style: "solid" | "dashed";
  role: string;
  points: Point[];
}

export interface KpiItem {
  id: string;
  label: string;
  value: number | null;
  unit: string | null;
  display: string;
  formula: string;
  inputs: InputRef[];
  source: PointSource | null;
  kind: string;
  period: string | null;
  missing: MissingFigure | null;
}

export interface EvaluatedWidget {
  status: "ok" | "missing" | "error";
  template: string;
  title: string;
  spec_hash?: string;
  currency: string;
  granularity: string;
  periods: string[];
  period_labels: string[];
  series: EvaluatedSeries[];
  kpi: { primary: KpiItem; secondary: KpiItem[] } | null;
  mark_lines: { label: string; value: number; unit: string | null; formula: string; source: PointSource | null }[];
  missing: MissingFigure | null;
  missing_series: MissingFigure[];
  error: string | null;
  notes: string[];
}

export interface WidgetSpec {
  template: string;
  title: string;
  series: { ref: string; label?: string | null; axis?: "left" | "right"; style?: "solid" | "dashed" }[];
  [key: string]: unknown;
}

/** Point provenance as embedded by the backend in `option._provenance`. */
export interface Provenance {
  label: string;
  value: number | null;
  formula: string;
  period?: string | null;
  kind?: string;
  inputs: InputRef[];
  source: PointSource | null;
}

export type EChartsOptionJson = Record<string, unknown> & {
  _provenance?: Record<string, Record<string, Provenance>>;
  _meta?: {
    status?: string;
    template?: string;
    currency?: string;
    periods?: string[];
    period_labels?: string[];
    units?: Record<string, string | null>;
    y_units?: (string | null)[];
    rows?: string[];
    notes?: string[];
    [key: string]: unknown;
  };
};

export interface Widget {
  id: string;
  role: string;
  spec: WidgetSpec;
  status: "ok" | "missing" | "error";
  evaluated: EvaluatedWidget;
  option: EChartsOptionJson | null;
  created_by: "system" | "vik" | "founder";
}

export interface LayoutItem {
  widget_id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Dashboard-wide zoom: months (YYYY-MM) resolved by the backend against the data's latest period. */
export interface TimeRange {
  last_months?: number;
  from: string;
  to: string;
  label: string;
}

export interface Dashboard {
  id: string;
  engagement_id: string;
  version: number;
  company: string;
  /** Every money figure is in this currency, converted at Bank of Canada rates when it isn't the reporting one. */
  currency: string;
  reporting_currency: string;
  currencies: { code: string; name: string; symbol: string }[];
  /** What building the model left out or reinterpreted (short quarters, missing exchange rates), from the metrics engine. */
  model_notes?: string[];
  layout: LayoutItem[];
  reserved: { id: string; x: number; y: number; w: number; h: number }[];
  time_range: TimeRange | null;
  widgets: Widget[];
}

export interface WidgetPreview {
  evaluated: EvaluatedWidget;
  option: EChartsOptionJson | null;
}

/** POST /dashboards/{id}/chat. `reply` never carries a figure; `dashboard` is set when something changed. */
export interface ChatResult {
  kind: "answer" | "widget_added" | "exists" | "missing" | "error" | "time_range" | "question" | "none";
  reply: string;
  spec: WidgetSpec | null;
  widget_id: string | null;
  missing: MissingFigure | null;
  time_range: TimeRange | null;
  dashboard: Dashboard | null;
  /** Answers: footnotes for every number in `reply` (computed by code, checked by the audit). */
  citations?: Citation[];
  /** Answers: follow-up questions worth asking next. */
  suggestions?: string[];
  /** Answers: a chat request that would chart what was asked about, e.g. "show total revenue by month". */
  chart?: string | null;
  /** Answers: retrieval couldn't find it in the notes. Searching every note with AI runs only if the user
   *  accepts (POST /dashboards/{id}/chat/catch-all); see docs/08-RAG.md §Asking permission. */
  offer?: CatchAllOffer | null;
}

export interface CatchAllOffer {
  kind: "catch_all";
  id: string;
  prompt: string;
  notes: number;
  expires_at: string;
}

// ---------------------------------------------------------------- the Areopagus

export interface PersonaSummary {
  id: string;
  name: string;
  firm: string;
  archetype: string;
  glyph: string;
  bio: string;
  lens: string;
  signature_move: string;
  priorities: Record<string, number>;
  style: { tone?: string; interrupt_tendency?: number; follow_up_depth?: number; aggression?: number; [k: string]: unknown };
  kits: string[];
  cheque_role?: string;
  builtin: boolean;
  base_archetype: string | null;
  version: number;
}

/** The full persona spec (`VCPersona` in backend/vik/areopagus/schema.py). A type alias so it's a `Json` body. */
export type VCPersonaSpec = {
  id: string;
  name: string;
  firm: string;
  archetype: string;
  glyph: string;
  bio: string;
  cheque_role: string;
  priorities: Record<string, number>;
  style: { tone: string; interrupt_tendency: number; follow_up_depth: number; aggression: number };
  signature_move: string;
  method: string;
  question_seeds: string[];
  dealbreakers: string[];
  kits: string[];
  base_archetype: string | null;
  builtin: boolean;
  version: number;
};

/** What the builder form offers (GET /areopagus/options). */
export interface PersonaOptions {
  lenses: { id: string; label: string }[];
  glyphs: string[];
  cheque_roles: string[];
}

/** A draft from a description (POST /areopagus/generate); `id` is "draft" until saved. */
export interface GenerateResult {
  persona: VCPersonaSpec;
  source: "gemini" | "heuristic";
}

// ---------------------------------------------------------------- court

export type ClaimStatus = "matches" | "contradicts" | "unsupported" | "forecast_as_fact";

export const CLAIM_LABEL: Record<ClaimStatus, string> = {
  matches: "Matches",
  contradicts: "Contradicts",
  unsupported: "Unsupported",
  forecast_as_fact: "Forecast as fact",
};

export interface Citation {
  marker: number;
  /** The cited span as it appears in the turn text, at [start, end). */
  text: string;
  start?: number;
  end?: number;
  kind?: string;
  figure_id?: string | null;
  source_id?: string | null;
  label: string;
  display?: string | null;
  formula: string;
  source: Source | Record<string, unknown> | null;
  url?: string | null;
}

export type TurnKind = "intro" | "question" | "answer" | "interject" | "coach" | "debrief";

export interface Turn {
  seq: number;
  speaker: string;
  speaker_name: string;
  kind: TurnKind;
  text: string;
  lens: string | null;
  hypothesis_id: string | null;
  intent: string | null;
  citations: Citation[];
  /** Vik's review of the drafted line, before it was spoken (questions only). */
  review?: LineReview | null;
  created_at: string;
}

export interface LineReview {
  verdict: "approve" | "revise";
  issues: string[];
  note: string;
  /** True when Vik sent the draft back and the investor rewrote it. */
  revised: boolean;
  source: "code" | "llm";
}

export type KnowledgeVerdict = "knows" | "partial" | "contradicts" | "missed" | "unverified";

/** Vik's check of a knowledge answer against the founder's own notes (via retrieval). */
export interface KnowledgeCheck {
  turn_seq: number | null;
  question_seq: number | null;
  vc_id: string;
  lens: string | null;
  verdict: KnowledgeVerdict;
  label: string;
  explanation: string;
  citations: Citation[];
  expected: { cite?: string; path?: string; heading?: string | null; title?: string; quote?: string };
  retrieval: { confidence: number | null; build_id: string | null; passages: number } | null;
}

export interface ScoreDims {
  evidence: number;
  clarity: number;
  composure: number;
  investor_fit: number;
}

export interface Score {
  turn_seq: number;
  accuracy: number | null;
  dims: ScoreDims;
  rationale: {
    good: string;
    missing: string;
    correct_figure: Figure | null;
    strong_answer: string;
    why_asked: string;
  };
}

export interface Claim {
  turn_seq: number;
  text: string;
  metric: string;
  value: number;
  unit: string;
  status: ClaimStatus;
  explanation: string;
  figure_id: string | null;
}

export interface Session {
  id: string;
  status: "live" | "ended";
  mode: "simulate";
  panel: PersonaSummary[];
  settings: { question_cap: number; coaching: "coached" | "realistic"; focus?: string | null; knowledge?: boolean };
  turns: Turn[];
  scores: Score[];
  claims: Claim[];
  knowledge?: KnowledgeCheck[];
  /** Knowledge questions written from the notes at start (0 when there's no search index), and how many are left. */
  knowledge_ready?: { on: boolean; probes: number; left: number };
  question_count: number;
  awaiting: "founder" | "panel" | null;
  next_speaker: string | null;
  report_id: string | null;
  started_at?: string;
}

// ---------------------------------------------------------------- reports

export interface ReportSummary {
  id: string;
  session_id: string;
  created_at: string;
  overall: number | null;
  readiness: string | null;
  company: string;
  dims?: ReportDims;
  delta?: number | null;
  /** One phrase built by code: the session focus, or the lenses pressed hardest. */
  summary?: string;
  vcs?: { id: string; name: string | null }[];
}

export interface ReportDims {
  accuracy?: number | null;
  evidence?: number | null;
  clarity?: number | null;
  composure?: number | null;
  investor_fit?: number | null;
  [k: string]: number | null | undefined;
}

export interface ReportSource {
  n: number;
  kind: string;
  ref?: string;
  url?: string;
  publisher?: string;
  title?: string;
  label?: string;
  formula?: string;
  as_of?: string;
}

export interface Report {
  id: string;
  markdown?: string;
  company?: string;
  session_id?: string;
  created_at?: string;
  verdict: { readiness: string; overall: number | null; dims: ReportDims; delta: number | null; summary?: string; questions?: number };
  per_vc: { vc_id: string; name?: string; verdict: string; second_meeting: boolean }[];
  questions: {
    turn_id?: string;
    turn_seq?: number;
    seq?: number;
    lens?: string | null;
    vc_id?: string;
    vc_name?: string;
    question: string;
    why_asked: string;
    answer: string;
    scores: ReportDims;
    good: string;
    missing: string;
    correct_figure: Figure | null;
    strong_answer: string;
    citations: Citation[];
  }[];
  ledger: (Partial<Claim> & { status: ClaimStatus; text: string; figure?: Figure | null })[];
  slides?: { slide: number; note: string; reword?: string }[];
  delivery?: { talk_time_s?: number; fillers?: number; slide_seconds?: number[]; dodged?: unknown[] } | null;
  knowledge_gaps?: { term: string; text: string; source_id?: string | null }[];
  /** Knowledge checks: what the founder recalled of their own notes, and Vik's verdict. */
  knowledge?: { vc_id: string; vc_name: string; question: string; answer: string; verdict: KnowledgeVerdict;
    explanation: string; path?: string | null; citations: Citation[] }[];
  action_plan: { priority: number; text: string; lens?: string | null }[];
  audit_notes?: { changed: string; why: string }[];
  sources: ReportSource[];
}

// ---------------------------------------------------------------- knowledge base

export type KbKind = "table" | "document" | "note" | "hub";

export interface KbNote {
  id: string;
  path: string;
  folder: string;
  title: string;
  kind: KbKind;
  format: "md" | "csv";
  tags: string[];
  summary: string;
  /** Related-note paths set by the organizer or the founder (wikilinks in the content are separate). */
  links: string[];
  meta: Record<string, unknown>;
  author: "import" | "ai" | "founder";
  file_id: string | null;
  size: number;
  version: number;
  organized_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KbLinkRef {
  id: string | null;
  path: string | null;
  title: string;
}

export interface KbNoteDetail extends KbNote {
  content: string;
  backlinks: KbLinkRef[];
  outlinks: KbLinkRef[];
  file?: { id: string; filename: string; kind: string; size: number; status: string } | null;
}

export interface KbGraphNode {
  id: string;
  title: string;
  path: string | null;
  kind: KbKind | "missing";
  folder: string;
  tags: string[];
  author: string | null;
  degree: number;
}

export interface KbGraph {
  nodes: KbGraphNode[];
  links: { source: string; target: string; type: "link" | "related" }[];
}

export interface KbJob {
  id: string;
  kind: "kb_ingest" | "kb_organize";
  status: "queued" | "running" | "done" | "failed" | "stale";
  error: string | null;
  result: Record<string, unknown> | null;
  enqueued_at: string;
  finished_at: string | null;
}

export interface KbStatus {
  notes: number;
  hubs: number;
  tables: number;
  documents: number;
  unorganized: number;
  organized_at: string | null;
  files: number;
  failed: number;
  bytes: number;
  jobs: KbJob[];
  running: boolean;
  failures: { id: string; filename: string; error: string | null }[];
  ocr: boolean;
  llm: boolean;
  /** The search index built by Fill dashboard (docs/08-RAG.md §Indexing). */
  index?: KbIndexStatus;
}

export interface KbIndexStatus {
  status: "none" | "building" | "ready" | "failed";
  build_id: string | null;
  built_at: string | null;
  notes: number;
  chunks: number;
  vectors: boolean;
  /** Notes edited or added since the last Fill: search doesn't reflect them until the next one. */
  changed_since: number;
  latest?: { id: string; status: string; error: string | null } | null;
}

export interface KbImportResult {
  job_id: string | null;
  files: { filename: string; status: "stored" | "duplicate" | "failed"; error?: string; id?: string }[];
}

export interface KbAutofill {
  engagement: Engagement;
  by: "gemini" | "heuristic";
  profile: { field: string; value: unknown; evidence: string }[];
  added: { note: string; as: string }[];
  skipped: { note: string; reason: string }[];
  /** The search index as it stands (Fill no longer rebuilds it: confirming the knowledge base does). */
  index?: KbIndexStatus;
}

// ---------------------------------------------------------------- pitch room (Simulation)

/** One claim in the pitch ledger: from the deck's pre-scan or said out loud, checked by code. */
export interface LedgerRow {
  id: string;
  slide: number | null;
  source: "deck" | "spoken";
  t_ms: number | null;
  text: string;
  metric: string | null;
  value: number | null;
  unit: string | null;
  status: ClaimStatus;
  explanation: string;
  figure_id: string | null;
  /** What the data says (the engine's figure, formatted), when there is one. */
  truth: string | null;
  truth_label: string | null;
}

/** How a statement from the pitch stands against the founder's own knowledge base. */
export type KbVerdict = "supported" | "contradicted" | "new" | "unclear";

/** A statement (shown on a slide or said out loud) checked against the knowledge base by retrieval. */
export interface KbCheck {
  id: string;
  slide: number | null;
  source: "deck" | "spoken";
  t_ms: number | null;
  text: string;
  topic: string;
  verdict: KbVerdict;
  /** Words copied from the note that support or contradict it (checked by code), with the note's path. */
  quote: string;
  path: string | null;
  cite: string | null;
  why: string;
}

export interface DeckSlide {
  n: number;
  text: string;
  /** The rendered page (JPEG data URL) of a PDF; null for a PowerPoint, shown as its title and lines. */
  image: string | null;
  title?: string;
  bullets?: string[];
  claims: LedgerRow[];
  kb?: KbCheck[];
}

export interface Deck {
  id: string;
  filename: string;
  kind?: "pdf" | "pptx";
  slides: DeckSlide[];
}

/** A line the room speaks: a persona id or "vik", and the words. */
export interface SpokenLine {
  speaker: string;
  text: string;
}

export interface JudgedScore {
  accuracy: number | null;
  dims: ScoreDims;
}

export interface PitchInterrupt {
  id: string;
  speaker: string;
  text: string;
  slide: number | null;
  t_ms: number;
  claim: LedgerRow | KbCheck;
  /** What the interrupt is about: a figure against the data, or a statement against the notes. */
  on?: "data" | "notes";
  reply: string | null;
  judged: JudgedScore | null;
  hand_back?: string;
}

export interface Pitch {
  id: string;
  mode: "live" | "after";
  status: "presenting" | "answering" | "qa" | "ended";
  panel: string[];
  deck_id: string | null;
  slides: number;
  ledger: LedgerRow[];
  /** Statements checked against the knowledge base, from the deck and said out loud. */
  kb?: KbCheck[];
  interrupts: PitchInterrupt[];
  pending: string | null;
  court_id: string | null;
  stats: { words: number; fillers: number } | null;
  /** Speaker id → ElevenLabs voice for this sitting (each seat's is its own). */
  voices?: Record<string, string>;
  say: SpokenLine[];
}
