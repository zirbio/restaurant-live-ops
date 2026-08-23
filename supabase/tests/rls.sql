begin;

create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;

-- Helpers locales y transaccionales: el proyecto parte sin una librería de
-- pruebas compartida y ninguna de estas funciones sobrevive al rollback.
create schema if not exists tests;

create or replace function tests.get_supabase_uid(username text)
returns uuid
language sql
immutable
set search_path = ''
as $$
  select (
    substr(md5(username), 1, 8) || '-' ||
    substr(md5(username), 9, 4) || '-' ||
    substr(md5(username), 13, 4) || '-' ||
    substr(md5(username), 17, 4) || '-' ||
    substr(md5(username), 21, 12)
  )::uuid;
$$;

create or replace function tests.create_supabase_user(username text)
returns uuid
language plpgsql
set search_path = ''
as $$
declare
  synthetic_uid uuid := tests.get_supabase_uid(username);
begin
  insert into auth.users (
    id,
    aud,
    role,
    email,
    encrypted_password,
    email_confirmed_at,
    raw_app_meta_data,
    raw_user_meta_data,
    created_at,
    updated_at
  ) values (
    synthetic_uid,
    'authenticated',
    'authenticated',
    username || '@example.test',
    '',
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{}'::jsonb,
    now(),
    now()
  );
  return synthetic_uid;
end;
$$;

create or replace function tests.authenticate_as(username text)
returns void
language plpgsql
set search_path = ''
as $$
declare
  synthetic_uid uuid := tests.get_supabase_uid(username);
begin
  perform set_config('request.jwt.claim.sub', synthetic_uid::text, true);
  perform set_config('request.jwt.claim.role', 'authenticated', true);
  perform set_config(
    'request.jwt.claims',
    jsonb_build_object('sub', synthetic_uid, 'role', 'authenticated')::text,
    true
  );
end;
$$;

select plan(38);

select tests.create_supabase_user('user_a');
select tests.create_supabase_user('user_b');

insert into public.restaurants (id, name) values
  ('R001', 'Centro'),
  ('R002', 'Norte')
on conflict (id) do update set name = excluded.name;

insert into public.app_user_access (user_id, restaurant_id) values
  (tests.get_supabase_uid('user_a'), 'R001'),
  (tests.get_supabase_uid('user_b'), 'R002');

insert into public.sales_hourly (
  restaurant_id, source_date, sales_date, calendar_date, hour, fold,
  net, captured_at, source
) values
  ('R001', '2026-01-02', '2026-01-02', '2026-01-02', 10, 0,
   10.00, '2026-01-02T11:00:00Z', 'live'),
  ('R002', '2026-01-02', '2026-01-02', '2026-01-02', 10, 0,
   20.00, '2026-01-02T11:00:00Z', 'live');

insert into public.sales_daily_totals (
  restaurant_id, sales_date, net, hourly_net_sum, captured_at, source, quality
) values
  ('R001', '2026-01-02', 10.00, 10.00, '2026-01-02T11:00:00Z', 'live', 'clean'),
  ('R002', '2026-01-02', 20.00, 20.00, '2026-01-02T11:00:00Z', 'live', 'clean');

insert into public.ingest_runs (
  restaurant_id, source, started_at, finished_at, status, error
) values
  ('R001', 'sales', '2026-01-02T10:00:00Z', '2026-01-02T10:01:00Z', 'ok', null),
  ('R002', 'sales', '2026-01-02T10:00:00Z', '2026-01-02T10:01:00Z', 'error',
   'fallo sintético');

insert into public.monthly_snapshots (
  restaurant_id, year, month, covers_through, net_sales, labor_cost, captured_at
) values
  ('R001', 2026, 1, '2026-01-02', 10.00, 2.00, '2026-01-03T06:00:00Z'),
  ('R002', 2026, 1, '2026-01-02', 20.00, 4.00, '2026-01-03T06:00:00Z');

select throws_ok(
  $$
    insert into public.ingest_runs (
      restaurant_id, source, started_at, finished_at, status
    ) values (
      'R001', 'sales', '2026-01-03T08:00:00Z', '2026-01-03T08:01:00Z', 'running'
    )
  $$,
  '23514',
  'new row for relation "ingest_runs" violates check constraint "ingest_runs_state_coherent"',
  'running no puede tener cierre'
);

select throws_ok(
  $$
    insert into public.ingest_runs (
      restaurant_id, source, started_at, status
    ) values ('R001', 'sales', '2026-01-03T08:00:00Z', 'ok')
  $$,
  '23514',
  'new row for relation "ingest_runs" violates check constraint "ingest_runs_state_coherent"',
  'ok exige cierre'
);

select throws_ok(
  $$
    insert into public.ingest_runs (
      restaurant_id, source, started_at, finished_at, status, error
    ) values (
      'R001', 'sales', '2026-01-03T08:00:00Z', '2026-01-03T08:01:00Z', 'error', ''
    )
  $$,
  '23514',
  'new row for relation "ingest_runs" violates check constraint "ingest_runs_state_coherent"',
  'error exige motivo no vacío'
);

select throws_ok(
  $$
    insert into public.ingest_runs (
      restaurant_id, source, started_at, finished_at, status
    ) values (
      'R001', 'sales', '2026-01-03T08:00:00Z', '2026-01-03T07:59:00Z', 'ok'
    )
  $$,
  '23514',
  'new row for relation "ingest_runs" violates check constraint "ingest_runs_finished_after_started"',
  'el cierre no puede preceder al inicio'
);

select throws_ok(
  $$
    insert into public.monthly_snapshots (
      restaurant_id, year, month, covers_through, net_sales, labor_cost, captured_at
    ) values (
      'R001', 2026, 1, '2026-02-01', 10.00, 2.00, '2026-02-02T06:00:00Z'
    )
  $$,
  '23514',
  'new row for relation "monthly_snapshots" violates check constraint "monthly_snapshots_covers_period"',
  'covers_through pertenece al mes declarado'
);

select results_eq(
  $$
    select tablename::text collate "C"
    from pg_catalog.pg_tables
    where schemaname = 'public'
    order by tablename
  $$,
  $$ values
    ('app_user_access'::text collate "C"),
    ('ingest_runs'::text collate "C"),
    ('monthly_snapshots'::text collate "C"),
    ('restaurants'::text collate "C"),
    ('sales_daily_totals'::text collate "C"),
    ('sales_hourly'::text collate "C"),
    ('workforce_projection_hourly'::text collate "C"),
    ('workforce_staffing_hourly'::text collate "C")
  $$,
  'public contiene exactamente las ocho tablas del contrato'
);

select ok(
  to_regclass('private.allowed_email') is not null,
  'la allowlist vive en private.allowed_email'
);

select ok(
  (
    select is_nullable = 'NO'
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'ingest_runs'
      and column_name = 'restaurant_id'
  ),
  'cada ciclo de ingesta pertenece obligatoriamente a un restaurante'
);

select results_eq(
  $$
    select column_name::text collate "C"
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'sales_hourly'
      and column_name in ('source_date', 'sales_date', 'calendar_date', 'hour', 'fold')
    order by ordinal_position
  $$,
  $$ values
    ('source_date'::text collate "C"),
    ('sales_date'::text collate "C"),
    ('calendar_date'::text collate "C"),
    ('hour'::text collate "C"),
    ('fold'::text collate "C")
  $$,
  'la hora conserva fecha de origen, jornada 06→06, fecha civil y fold'
);

select results_eq(
  $$
    select pg_get_constraintdef(oid)::text
    from pg_catalog.pg_constraint
    where conrelid = 'public.sales_hourly'::regclass
      and contype = 'p'
  $$,
  $$ values (
    'PRIMARY KEY (restaurant_id, source_date, calendar_date, hour, fold)'::text
  ) $$,
  'la clave horaria preserva origen y ambas ocurrencias DST'
);

select results_eq(
  $$
    select relname::text collate "C"
    from pg_catalog.pg_class
    join pg_catalog.pg_namespace on pg_namespace.oid = pg_class.relnamespace
    where pg_namespace.nspname = 'public'
      and pg_class.relkind = 'r'
      and pg_class.relrowsecurity
    order by relname
  $$,
  $$ values
    ('app_user_access'::text collate "C"),
    ('ingest_runs'::text collate "C"),
    ('monthly_snapshots'::text collate "C"),
    ('restaurants'::text collate "C"),
    ('sales_daily_totals'::text collate "C"),
    ('sales_hourly'::text collate "C"),
    ('workforce_projection_hourly'::text collate "C"),
    ('workforce_staffing_hourly'::text collate "C")
  $$,
  'RLS está activo en todas las tablas públicas'
);

select tests.authenticate_as('user_a');
set local role authenticated;

select results_eq(
  $$ select id collate "C" from public.restaurants order by id $$,
  $$ values ('R001'::text collate "C") $$,
  'user_a solo ve R001'
);

select results_eq(
  $$ select restaurant_id collate "C" from public.sales_hourly order by restaurant_id $$,
  $$ values ('R001'::text collate "C") $$,
  'user_a puede leer su propia venta'
);

select is_empty(
  $$ select * from public.sales_hourly where restaurant_id = 'R002' $$,
  'user_a no ve venta de R002'
);

select is_empty(
  $$ select * from public.ingest_runs where restaurant_id = 'R002' $$,
  'los errores también quedan aislados'
);

select results_eq(
  $$ select restaurant_id collate "C" from public.ingest_runs order by restaurant_id $$,
  $$ values ('R001'::text collate "C") $$,
  'user_a ve la frescura de su restaurante'
);

select results_eq(
  $$ select restaurant_id collate "C" from public.monthly_snapshots order by restaurant_id $$,
  $$ values ('R001'::text collate "C") $$,
  'la lectura mensual también queda aislada'
);

reset role;

set local role anon;
select throws_ok(
  $$ select * from public.restaurants $$,
  '42501',
  'permission denied for table restaurants',
  'anon no puede consultar restaurantes'
);
reset role;

select is_empty(
  $$
    with objects(schema_name, table_name) as (values
      ('public', 'restaurants'),
      ('public', 'app_user_access'),
      ('public', 'sales_hourly'),
      ('public', 'sales_daily_totals'),
      ('public', 'workforce_projection_hourly'),
      ('public', 'workforce_staffing_hourly'),
      ('public', 'ingest_runs'),
      ('public', 'monthly_snapshots'),
      ('private', 'allowed_email')
    ), privileges(privilege_name) as (values
      ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')
    )
    select schema_name, table_name, privilege_name
    from objects cross join privileges
    where has_table_privilege(
      'anon', format('%I.%I', schema_name, table_name), privilege_name
    )
  $$,
  'la matriz anon no concede CRUD sobre ninguna tabla pública ni la allowlist'
);

select is_empty(
  $$
    with roles(role_name) as (values
      ('anon'), ('sales_ingest_worker'), ('workforce_ingest_worker')
    ), functions(signature) as (values
      ('private.can_read_restaurant(text)'),
      ('private.restrict_signup_to_allowlist(jsonb)')
    )
    select role_name, signature
    from roles cross join functions
    where has_function_privilege(role_name, signature, 'EXECUTE')
  $$,
  'anon y los workers no ejecutan funciones privadas de autorización'
);

select ok(
  not has_table_privilege('authenticated', 'public.app_user_access', 'INSERT'),
  'el navegador no puede conceder accesos'
);

select ok(
  has_table_privilege(
    'sales_ingest_worker', 'public.sales_hourly', 'SELECT,INSERT,UPDATE,DELETE'
  ),
  'el rol de venta puede hacer upsert en su tabla horaria'
);
select ok(
  not has_table_privilege('sales_ingest_worker', 'public.workforce_projection_hourly', 'INSERT'),
  'el rol de venta no escribe previsiones de personal'
);
select ok(
  not has_table_privilege('sales_ingest_worker', 'public.app_user_access', 'INSERT'),
  'el rol de venta no modifica autorizaciones'
);
select ok(
  not has_table_privilege('sales_ingest_worker', 'private.allowed_email', 'INSERT'),
  'el rol de venta no modifica la allowlist'
);
select ok(
  has_table_privilege('workforce_ingest_worker', 'public.workforce_projection_hourly', 'SELECT')
  and has_table_privilege(
    'workforce_ingest_worker', 'public.workforce_projection_hourly', 'INSERT'
  )
  and has_table_privilege(
    'workforce_ingest_worker', 'public.workforce_projection_hourly', 'UPDATE'
  )
  and not has_table_privilege(
    'workforce_ingest_worker', 'public.workforce_projection_hourly', 'DELETE'
  ),
  'el rol de personal refresca previsiones sin permiso de borrado'
);
select ok(
  not has_table_privilege('workforce_ingest_worker', 'public.sales_hourly', 'INSERT'),
  'el rol de personal no escribe venta'
);
select ok(
  not has_table_privilege('workforce_ingest_worker', 'public.app_user_access', 'INSERT'),
  'el rol de personal no modifica autorizaciones'
);
select ok(
  not has_table_privilege('workforce_ingest_worker', 'private.allowed_email', 'INSERT'),
  'el rol de personal no modifica la allowlist'
);
select ok(
  not has_table_privilege('sales_ingest_worker', 'public.monthly_snapshots', 'INSERT')
  and not has_table_privilege('workforce_ingest_worker', 'public.monthly_snapshots', 'INSERT'),
  'los roles diarios no pueden escribir el contrato mensual'
);

select is_empty(
  $$
    with roles(role_name) as (values
      ('sales_ingest_worker'), ('workforce_ingest_worker')
    ), objects(object_name) as (values
      ('public.restaurants'),
      ('public.app_user_access'),
      ('public.sales_hourly'),
      ('public.sales_daily_totals'),
      ('public.workforce_projection_hourly'),
      ('public.workforce_staffing_hourly'),
      ('public.ingest_runs'),
      ('public.monthly_snapshots'),
      ('private.allowed_email')
    ), privileges(privilege_name) as (values
      ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')
    ), actual as (
      select role_name, object_name, privilege_name
      from roles cross join objects cross join privileges
      where has_table_privilege(role_name, object_name, privilege_name)
    ), expected as (
      select 'sales_ingest_worker'::text as role_name,
             object_name::text,
             privilege_name::text
      from (values ('public.sales_hourly'), ('public.sales_daily_totals')) domain(object_name)
      cross join privileges
      union all
      select 'sales_ingest_worker', 'public.ingest_runs', privilege_name
      from privileges where privilege_name <> 'DELETE'
      union all
      select 'workforce_ingest_worker', object_name, privilege_name
      from (
        values
          ('public.workforce_projection_hourly'),
          ('public.workforce_staffing_hourly')
      ) domain(object_name)
      cross join privileges
      where privilege_name <> 'DELETE'
      union all
      select 'workforce_ingest_worker', 'public.ingest_runs', privilege_name
      from privileges where privilege_name <> 'DELETE'
    ), differences as (
      (select * from actual except select * from expected)
      union all
      (select * from expected except select * from actual)
    )
    select * from differences
  $$,
  'la matriz CRUD de workers es exacta y separa ambos dominios'
);

select ok(
  has_function_privilege(
    'supabase_auth_admin',
    'private.restrict_signup_to_allowlist(jsonb)',
    'EXECUTE'
  ),
  'solo el administrador de Auth puede ejecutar el hook'
);
select ok(
  not exists (
    select 1
    from pg_catalog.pg_proc
    cross join lateral aclexplode(
      coalesce(pg_proc.proacl, acldefault('f', pg_proc.proowner))
    ) as privilege
    where pg_proc.oid = 'private.restrict_signup_to_allowlist(jsonb)'::regprocedure
      and privilege.grantee = 0
      and privilege.privilege_type = 'EXECUTE'
  ),
  'PUBLIC no puede ejecutar el hook'
);
select ok(
  not has_function_privilege(
    'anon',
    'private.restrict_signup_to_allowlist(jsonb)',
    'EXECUTE'
  ),
  'anon no puede ejecutar el hook'
);
select ok(
  not has_function_privilege(
    'authenticated',
    'private.restrict_signup_to_allowlist(jsonb)',
    'EXECUTE'
  ),
  'authenticated no puede ejecutar el hook'
);

select ok(
  has_function_privilege(
    'authenticated',
    'private.can_read_restaurant(text)',
    'EXECUTE'
  ),
  'authenticated puede usar el predicado de autorización'
);
select ok(
  not has_function_privilege('anon', 'private.can_read_restaurant(text)', 'EXECUTE'),
  'anon no puede invocar el predicado de autorización'
);

select ok(
  to_regclass('public.legacy_hourly') is null
  and to_regclass('public.legacy_projection_hourly') is null
  and to_regclass('public.legacy_versioned_cutovers') is null,
  'no quedan tablas de compatibilidad ni cutovers heredados'
);

select * from finish();
rollback;
