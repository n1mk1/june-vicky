-- Retrieval over the knowledge base (docs/08-RAG.md). Each Fill dashboard builds a new index
-- (kb_index_builds + kb_chunks) and discards the old one. Vectors need pgvector: when the extension
-- can't be created, the tables are made without vector columns and search runs on BM25 only.
-- Idempotent.

alter type job_kind add value if not exists 'kb_index';

-- The vault's version: bumped by a trigger on every change to kb_notes, so no write path can miss it.
-- Cache keys include it, so an edit makes every cached retrieval and answer unreachable.
create table if not exists kb_meta (
  id boolean primary key default true check (id),
  version bigint not null default 0
);
insert into kb_meta (id, version) values (true, 0) on conflict (id) do nothing;

create or replace function kb_bump_version() returns trigger language plpgsql as $$
begin
  update kb_meta set version = version + 1 where id;
  return null;
end $$;

do $$ begin
  create trigger kb_notes_version after insert or update or delete on kb_notes
    for each statement execute function kb_bump_version();
exception when duplicate_object then null;
end $$;

-- One row per index build, started by Fill dashboard (or scripts/kb_reindex.py).
create table if not exists kb_index_builds (
  id uuid primary key default gen_random_uuid(),
  engagement_id uuid references engagements(id) on delete set null,  -- the draft the Fill created
  job_id uuid,
  status text not null default 'queued',    -- queued → building → active → superseded | failed | cancelled
  notes int not null default 0,
  chunks int not null default 0,
  embedded int not null default 0,          -- chunks sent to Voyage
  reused int not null default 0,            -- vectors copied from identical chunks of the build it replaces
  embed_model text,
  error text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists kb_index_builds_created on kb_index_builds (created_at desc);
create unique index if not exists kb_index_builds_one_active on kb_index_builds ((true)) where status = 'active';

create table if not exists kb_chunks (
  id uuid primary key default gen_random_uuid(),
  build_id uuid not null references kb_index_builds(id) on delete cascade,
  note_id uuid not null references kb_notes(id) on delete cascade,
  note_md5 text not null,                   -- md5(kb_notes.content) when cut; a mismatch means the note changed
  ord int not null,                         -- position in the note
  heading text not null default '',         -- "Page 4", "Slide 7: Traction", "Churn"
  start_char int not null,                  -- span in kb_notes.content (Python string offsets)
  end_char int not null,
  text text not null,                       -- = content[start_char:end_char]
  text_sha256 text not null,                -- of text alone: the same passage in two notes
  sha256 text not null,                     -- of the embedded text (context + chunk): vector reuse
  embed_model text,
  created_at timestamptz not null default now(),
  unique (build_id, note_id, ord)
);
create index if not exists kb_chunks_build on kb_chunks (build_id);
create index if not exists kb_chunks_note on kb_chunks (note_id);
create index if not exists kb_chunks_sha on kb_chunks (sha256);

-- Semantic answer cache (docs/08-RAG.md §Caching). Rows belong to a build and go with it.
create table if not exists qa_cache (
  id uuid primary key default gen_random_uuid(),
  build_id uuid not null references kb_index_builds(id) on delete cascade,
  kb_version bigint not null,
  truthpack_id uuid,
  truthpack_version int,
  question text not null,
  question_norm text not null,
  guard text not null,                      -- digits, periods and metric words in the question
  answer jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists qa_cache_created on qa_cache (created_at);

-- Every catch-all offer (docs/08-RAG.md §Learning from misses). Kept after its build is gone.
create table if not exists rag_misses (
  id uuid primary key default gen_random_uuid(),
  build_id uuid references kb_index_builds(id) on delete set null,
  kb_version bigint not null,
  surface text not null default 'ask',
  dashboard_id uuid,
  question text not null,
  retrieved jsonb not null default '{}'::jsonb,
  decision text not null default 'pending', -- pending | accepted | declined | expired
  decided_at timestamptz,
  passed boolean,
  cited_notes text[] not null default '{}',
  reviewed boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists rag_misses_created on rag_misses (created_at desc);

-- A table or document that Fill dashboard sent to the intake pipeline remembers its note, so a figure's
-- citation can name the knowledge-base note it came from.
alter table uploads add column if not exists kb_note_id uuid references kb_notes(id) on delete set null;

-- Vectors, when pgvector is available (Render; locally the pgvector/pgvector image).
do $$ begin
  create extension if not exists vector;
exception when others then
  raise notice 'pgvector not available (%); knowledge-base search runs on BM25 only', sqlerrm;
end $$;

do $$ begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    alter table kb_chunks add column if not exists embedding halfvec(1024);
    create index if not exists kb_chunks_embedding on kb_chunks using hnsw (embedding halfvec_cosine_ops);
    alter table qa_cache add column if not exists embedding halfvec(1024);
    create index if not exists qa_cache_embedding on qa_cache using hnsw (embedding halfvec_cosine_ops);
  end if;
end $$;
