-- Vik chairs the court: she reviews every investor line before it is spoken (stored in turns.audit.review)
-- and verifies the founder's answers to knowledge questions against their own notes, through retrieval.

-- One row per knowledge question answered: what the notes say, what the founder said, Vik's verdict.
create table if not exists knowledge_checks (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  turn_id uuid references turns(id) on delete cascade,           -- the founder's answer
  question_turn_id uuid references turns(id) on delete set null, -- the knowledge question
  probe_id text not null,
  vc_id text not null,
  lens text,
  verdict text not null,          -- knows | partial | contradicts | missed | unverified
  explanation text not null,      -- audited; quotes a note only word for word with its [kb:path] token
  expected jsonb not null,        -- {cite, path, heading, quote}: the passage the question was written from
  citations jsonb not null default '[]',
  retrieval jsonb,                -- {confidence, build_id, passages}: the check's own retrieval
  source text not null default 'offline',
  created_at timestamptz not null default now()
);
create index if not exists knowledge_checks_session on knowledge_checks (session_id, created_at);
