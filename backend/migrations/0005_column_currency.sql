-- A mapping's money unit is now the column's own currency, converted into the reporting currency at
-- Bank of Canada rates. Before, it was only a label copied from the profile, and every table was in
-- the company currency; existing mappings are set to that so nothing is converted by mistake.
create function pg_temp.with_currency(m jsonb, cur text) returns jsonb language sql immutable as $$
  select coalesce(jsonb_agg(case
    when lower(coalesce(e->>'unit', '')) in ('cad', 'usd', 'eur', 'gbp', 'aud', 'nzd', 'jpy', 'cny', 'hkd', 'sgd', 'twd',
                                             'krw', 'inr', 'idr', 'myr', 'thb', 'chf', 'nok', 'sek', 'pln', 'try', 'zar',
                                             'mxn', 'brl', 'pen')
      then e || jsonb_build_object('unit', lower(cur))
    else e end), '[]'::jsonb)
  from jsonb_array_elements(m) e
$$;

update dataset_mappings m
   set proposed = pg_temp.with_currency(m.proposed, p.currency),
       confirmed = case when m.confirmed is null then null else pg_temp.with_currency(m.confirmed, p.currency) end
  from datasets d
  join company_profiles p on p.engagement_id = d.engagement_id
 where d.id = m.dataset_id;
