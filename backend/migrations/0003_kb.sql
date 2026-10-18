-- Knowledge base: one global vault of markdown and CSV notes the AI organizes (docs/07-KNOWLEDGE-BASE.md).
-- kb_files keeps every original as uploaded; kb_notes holds the readable text made from them, plus
-- notes the founder writes and hub notes the organizer writes. Idempotent.

alter type job_kind add value if not exists 'kb_ingest';
alter type job_kind add value if not exists 'kb_organize';

create table if not exists kb_files (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  mime text not null default 'application/octet-stream',
  bytes bytea not null,
  size int not null default 0,
  sha256 text not null,
  kind text not null,
  status text not null default 'stored',  -- stored → converted | failed
  error text,
  created_at timestamptz not null default now()
);
create index if not exists kb_files_sha on kb_files (sha256);

create table if not exists kb_notes (
  id uuid primary key default gen_random_uuid(),
  path text not null unique,                -- "financials/income-statement.csv", folder/name.ext
  title text not null,
  kind text not null default 'note',        -- table | document | note | hub
  format text not null default 'md',        -- md | csv
  content text not null default '',
  file_id uuid references kb_files(id) on delete set null,
  tags text[] not null default '{}',
  summary text not null default '',
  links text[] not null default '{}',       -- resolved target paths, rebuilt on every write
  meta jsonb not null default '{}'::jsonb,  -- provenance: pages, ocr pages, sheet, columns, rows
  author text not null default 'import',    -- import | ai | founder
  organized_at timestamptz,
  version int not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists kb_notes_file on kb_notes (file_id);
create index if not exists kb_notes_updated on kb_notes (updated_at desc);

do $$ begin
  create trigger kb_notes_updated before update on kb_notes for each row execute function set_updated_at();
exception when duplicate_object then null;
end $$;
