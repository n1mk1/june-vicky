-- CAD is the default reporting currency (anything else converts at Bank of Canada rates).
alter table company_profiles alter column currency set default 'CAD';
