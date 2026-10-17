-- Columns the API needs that 0001 left out. Idempotent.
alter table datasets add column if not exists transposed boolean not null default false;
alter table datasets add column if not exists notes jsonb not null default '[]'::jsonb;
alter table datasets add column if not exists upload_kind text not null default 'csv';
alter table widgets add column if not exists role text not null default '';
alter table sessions add column if not exists question_count int not null default 0;
alter table reports add column if not exists readiness text;
create index if not exists reports_engagement on reports (engagement_id, created_at desc);
create index if not exists truthpacks_confirmed on truthpacks (engagement_id, confirmed_at desc);
