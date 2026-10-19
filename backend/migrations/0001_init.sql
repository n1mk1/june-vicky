-- Vik initial schema. See docs/05-BACKEND-SCHEMA.md.
create extension if not exists pgcrypto;

create or replace function set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

do $$ begin
  create type engagement_status as enum ('draft', 'active', 'archived');
  create type company_stage as enum ('pre_seed', 'seed', 'series_a', 'series_b_plus', 'other');
  create type business_model as enum ('recurring', 'other');
  create type period_granularity as enum ('month', 'quarter', 'year', 'none');
  create type upload_kind as enum ('csv', 'xlsx', 'pdf', 'docx', 'md', 'deck');
  create type upload_status as enum ('stored', 'parsed', 'extracted', 'failed');
  create type widget_status as enum ('ok', 'missing', 'error');
  create type widget_author as enum ('system', 'vik', 'founder');
  create type message_role as enum ('founder', 'vik', 'tool');
  create type session_mode as enum ('prepare', 'simulate');
  create type session_status as enum ('starting', 'live', 'paused', 'ended', 'failed');
  create type turn_kind as enum ('question', 'answer', 'interject', 'coach', 'debrief', 'segment', 'interrupt', 'intro');
  create type claim_status as enum ('matches', 'contradicts', 'unsupported', 'forecast_as_fact');
  create type memory_kind as enum ('weakness', 'answer', 'rewrite', 'drill');
  create type job_kind as enum ('memo', 'prescan', 'extract', 'report', 'persona_gen', 'audit');
  create type job_status as enum ('queued', 'running', 'done', 'failed', 'stale');
exception when duplicate_object then null;
end $$;

create table if not exists engagements (
  id uuid primary key default gen_random_uuid(),
  status engagement_status not null default 'draft',
  name text not null default '',
  truthpack_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  confirmed_at timestamptz,
  archived_at timestamptz
);
create unique index if not exists engagements_one_active on engagements (status) where status = 'active';

create table if not exists company_profiles (
  engagement_id uuid primary key references engagements(id) on delete cascade,
  name text not null default '',
  country char(2) not null default 'US',
  currency char(3) not null default 'USD',
  fiscal_year_start_month smallint not null default 1 check (fiscal_year_start_month between 1 and 12),
  stage company_stage not null default 'seed',
  round_type text,
  round_size numeric(14, 2),
  business_model business_model not null default 'recurring',
  granularity period_granularity not null default 'month',
  extra jsonb not null default '{}'::jsonb,
  inferred jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists uploads (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  filename text not null,
  mime text not null default 'application/octet-stream',
  bytes bytea not null,
  size int not null default 0,
  sha256 text not null,
  kind upload_kind not null,
  status upload_status not null default 'stored',
  error text,
  created_at timestamptz not null default now()
);
create index if not exists uploads_engagement on uploads (engagement_id, created_at desc);

create table if not exists datasets (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  upload_id uuid references uploads(id) on delete cascade,
  name text not null,
  period_axis text,
  granularity period_granularity not null default 'none',
  table_kind text not null default 'series',
  columns jsonb not null default '[]'::jsonb,
  rows jsonb not null default '[]'::jsonb,
  fingerprint text not null,
  created_at timestamptz not null default now()
);
create index if not exists datasets_engagement on datasets (engagement_id);

create table if not exists dataset_mappings (
  id uuid primary key default gen_random_uuid(),
  dataset_id uuid not null unique references datasets(id) on delete cascade,
  fingerprint text not null,
  proposed jsonb not null default '[]'::jsonb,
  confirmed jsonb,
  proposer text not null default 'heuristic',
  confirmed_at timestamptz
);
create index if not exists dataset_mappings_fingerprint on dataset_mappings (fingerprint);

create table if not exists truthpacks (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  facts jsonb not null default '[]'::jsonb,
  figures jsonb not null default '[]'::jsonb,
  coverage jsonb not null default '[]'::jsonb,
  attack_list jsonb not null default '[]'::jsonb,
  deck_claims jsonb not null default '[]'::jsonb,
  version int not null default 1,
  created_at timestamptz not null default now(),
  confirmed_at timestamptz
);
create index if not exists truthpacks_engagement on truthpacks (engagement_id, created_at desc);

do $$ begin
  alter table engagements add constraint engagements_truthpack_fk
    foreign key (truthpack_id) references truthpacks(id) on delete set null;
exception when duplicate_object then null;
end $$;

create table if not exists dashboards (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  name text not null default 'default',
  layout jsonb not null default '[]'::jsonb,
  time_range jsonb,
  version int not null default 1,
  updated_at timestamptz not null default now()
);
create index if not exists dashboards_engagement on dashboards (engagement_id);

create table if not exists widgets (
  id uuid primary key default gen_random_uuid(),
  dashboard_id uuid not null references dashboards(id) on delete cascade,
  spec jsonb not null,
  spec_hash text not null,
  option_cache jsonb,
  provenance jsonb not null default '[]'::jsonb,
  status widget_status not null default 'ok',
  missing jsonb,
  created_by widget_author not null default 'system',
  "order" int not null default 0,
  created_at timestamptz not null default now()
);
create unique index if not exists widgets_dashboard_spec on widgets (dashboard_id, spec_hash);

create table if not exists dashboard_messages (
  id uuid primary key default gen_random_uuid(),
  dashboard_id uuid not null references dashboards(id) on delete cascade,
  role message_role not null,
  content text not null default '',
  tool_calls jsonb not null default '[]'::jsonb,
  citations jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists dashboard_messages_dash on dashboard_messages (dashboard_id, created_at);

create table if not exists vc_personas (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  spec jsonb not null,
  base_archetype text,
  version int not null default 1,
  builtin boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists sessions (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  truthpack_id uuid references truthpacks(id) on delete set null,
  mode session_mode not null,
  panel text[] not null default '{}',
  settings jsonb not null default '{}'::jsonb,
  deck_upload_id uuid references uploads(id) on delete set null,
  deck jsonb,
  agenda jsonb not null default '[]'::jsonb,
  state jsonb not null default '{}'::jsonb,
  status session_status not null default 'starting',
  version int not null default 0,
  started_at timestamptz not null default now(),
  ended_at timestamptz
);
create index if not exists sessions_engagement on sessions (engagement_id, started_at desc);

create table if not exists memos (
  session_id uuid not null references sessions(id) on delete cascade,
  vc_id text not null,
  persona_version int not null default 1,
  truthpack_version int not null default 1,
  memo jsonb not null,
  thinking_snippets jsonb not null default '[]'::jsonb,
  usage jsonb,
  created_at timestamptz not null default now(),
  primary key (session_id, vc_id)
);
create index if not exists memos_cache on memos (vc_id, persona_version, truthpack_version);

create table if not exists turns (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  seq int not null,
  speaker text not null,
  kind turn_kind not null,
  intent text,
  hypothesis_id text,
  text text not null default '',
  citations jsonb not null default '[]'::jsonb,
  slide int,
  t_offset_ms int,
  audit jsonb,
  usage jsonb,
  created_at timestamptz not null default now(),
  unique (session_id, seq)
);
create index if not exists turns_speaker on turns (session_id, speaker);

create table if not exists beliefs (
  session_id uuid not null references sessions(id) on delete cascade,
  vc_id text not null,
  turn_seq int not null,
  state jsonb not null,
  bid numeric not null default 0,
  intent text,
  target_hyp text,
  primary key (session_id, vc_id, turn_seq)
);

create table if not exists chair_decisions (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  after_turn_seq int not null,
  candidates jsonb not null default '[]'::jsonb,
  decision jsonb not null,
  valid boolean not null default true,
  fallback boolean not null default false,
  latency_ms int not null default 0,
  reason text,
  created_at timestamptz not null default now()
);

create table if not exists claims (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  turn_id uuid references turns(id) on delete cascade,
  slide int,
  t_offset_ms int,
  text text not null,
  metric text,
  value numeric,
  unit text,
  period text,
  is_forecast boolean not null default false,
  status claim_status not null,
  figure_id text,
  figure jsonb,
  severity numeric not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists claims_status on claims (session_id, status);

create table if not exists scores (
  turn_id uuid primary key references turns(id) on delete cascade,
  question_turn_id uuid references turns(id) on delete set null,
  accuracy numeric,
  dims jsonb not null default '{}'::jsonb,
  rationale jsonb not null default '{}'::jsonb,
  judge_usage jsonb
);

create table if not exists reports (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null unique references sessions(id) on delete cascade,
  engagement_id uuid not null references engagements(id) on delete cascade,
  report jsonb not null,
  markdown text not null default '',
  overall numeric,
  dims jsonb not null default '{}'::jsonb,
  delta_vs_previous numeric,
  audit_notes jsonb not null default '[]'::jsonb,
  sources jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists founder_memory (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  kind memory_kind not null,
  lens text,
  topic text,
  payload jsonb not null default '{}'::jsonb,
  severity numeric,
  last_seen_at timestamptz not null default now()
);
create index if not exists founder_memory_lens on founder_memory (engagement_id, lens, last_seen_at desc);

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid references engagements(id) on delete cascade,
  session_id uuid references sessions(id) on delete cascade,
  kind job_kind not null,
  status job_status not null default 'queued',
  payload jsonb not null default '{}'::jsonb,
  result jsonb,
  error text,
  attempts int not null default 0,
  enqueued_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index if not exists jobs_status on jobs (status, enqueued_at);

create table if not exists sources (
  id text primary key,
  publisher text not null,
  title text,
  claim text not null,
  url text,
  as_of text,
  business_model text[] not null default '{}',
  stage text[] not null default '{}',
  topic text[] not null default '{}',
  verified boolean not null default false
);

create table if not exists spend (
  date date primary key,
  usd numeric not null default 0,
  calls int not null default 0
);

do $$ begin
  create trigger engagements_updated before update on engagements for each row execute function set_updated_at();
  create trigger company_profiles_updated before update on company_profiles for each row execute function set_updated_at();
  create trigger vc_personas_updated before update on vc_personas for each row execute function set_updated_at();
  create trigger dashboards_updated before update on dashboards for each row execute function set_updated_at();
exception when duplicate_object then null;
end $$;
