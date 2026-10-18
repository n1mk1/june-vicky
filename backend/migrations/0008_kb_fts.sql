-- Knowledge-base note search (QA KB-13): an expression GIN index for the full-text search in
-- vicky/kb/store.py (`FTS_DOC`), so `/kb/search` and the agents' keyword search stop scanning and
-- re-parsing every note. The expression must stay byte-for-byte the same as `FTS_DOC`. The text is capped
-- at 200,000 characters so a huge note's tsvector stays under Postgres's 1 MB limit (past it, the note's
-- insert would fail). Idempotent.

create index if not exists kb_notes_fts on kb_notes
  using gin (to_tsvector('simple', left(title || ' ' || summary || ' ' || content, 200000)));
