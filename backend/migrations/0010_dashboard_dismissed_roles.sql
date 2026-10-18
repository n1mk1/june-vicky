-- Default widgets the founder removed from a dashboard, by role (e.g. 'opex_mix'), so a later
-- confirm doesn't add them back. Idempotent.
alter table dashboards add column if not exists dismissed_roles text[] not null default '{}';
