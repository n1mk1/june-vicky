-- The chair and the dashboard assistant are now Vik. On a database made before the rebrand, the chair's old
-- enum label (the one label besides the current ones) is renamed in place to 'vik', and the chair's turns
-- (intro, coach and debrief are only ever the chair's) are re-attributed to 'vik'. A fresh database already
-- has 'vik', so this changes nothing there. Idempotent.
do $$
declare
  old text;
begin
  for old in
    select e.enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid
    where t.typname = 'widget_author' and e.enumlabel not in ('system', 'vik', 'founder')
  loop
    execute format('alter type widget_author rename value %L to %L', old, 'vik');
  end loop;
  for old in
    select e.enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid
    where t.typname = 'message_role' and e.enumlabel not in ('founder', 'vik', 'tool')
  loop
    execute format('alter type message_role rename value %L to %L', old, 'vik');
  end loop;
end $$;

update turns set speaker = 'vik' where kind in ('intro', 'coach', 'debrief') and speaker <> 'vik';
