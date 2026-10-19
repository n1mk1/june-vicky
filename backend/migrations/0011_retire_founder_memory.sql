-- Preparation (the text court) is gone, and with it founder memory: the questions marked to drill and the
-- weak spots carried into the next session. Sessions and reports already stored are kept (the Reports tab
-- still shows them); the `prepare` value stays in `session_mode` for those rows. Idempotent.
drop table if exists founder_memory;
drop type if exists memory_kind;
