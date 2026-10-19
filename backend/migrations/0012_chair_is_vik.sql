-- The chair and the dashboard assistant are now Vik. Rows written under the old name are renamed: the enum
-- labels in place (a fresh database already has 'vik'), and the chair's turns. Idempotent.
do $$ begin
  if exists (select 1 from pg_enum e join pg_type t on t.oid = e.enumtypid
             where t.typname = 'widget_author' and e.enumlabel = 'vicky') then
    alter type widget_author rename value 'vicky' to 'vik';
  end if;
  if exists (select 1 from pg_enum e join pg_type t on t.oid = e.enumtypid
             where t.typname = 'message_role' and e.enumlabel = 'vicky') then
    alter type message_role rename value 'vicky' to 'vik';
  end if;
end $$;

update turns set speaker = 'vik' where speaker = 'vicky';
