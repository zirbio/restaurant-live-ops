begin;

create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;

select plan(8);

select is(
  (
    select count(*)
    from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    where granted.rolname in ('sales_ingest_worker', 'workforce_ingest_worker')
      and (membership.set_option or membership.inherit_option)
  ),
  0::bigint,
  'los roles NOLOGIN no dejan membresías ejecutables'
);

select is(
  (
    select
      count(*) = 2
      and count(*) filter (
        where member_role.rolname = 'postgres'
          and grantor_role.rolname = 'supabase_admin'
          and membership.admin_option
          and not membership.set_option
          and not membership.inherit_option
      ) = 2
    from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles member_role on member_role.oid = membership.member
    join pg_catalog.pg_roles grantor_role on grantor_role.oid = membership.grantor
    where granted.rolname in ('sales_ingest_worker', 'workforce_ingest_worker')
  ),
  true,
  'solo existen las dos membresías ADMIN automáticas no ejecutables de PostgreSQL 17'
);

insert into public.restaurants (id, name)
values ('R001', 'Centro')
on conflict (id) do update set name = excluded.name;

set local role sales_ingest_worker;
do $$
declare
  run_id bigint;
begin
  insert into public.sales_hourly (
    restaurant_id, source_date, sales_date, calendar_date, hour, fold,
    net, captured_at, source
  ) values (
    'R001', '2035-01-03', '2035-01-03', '2035-01-03', 8, 0,
    30.00, '2035-01-03T09:00:00Z', 'live'
  );
  insert into public.sales_hourly (
    restaurant_id, source_date, sales_date, calendar_date, hour, fold,
    net, captured_at, source
  ) values (
    'R001', '2035-01-03', '2035-01-03', '2035-01-03', 8, 0,
    31.00, '2035-01-03T09:01:00Z', 'live'
  ) on conflict (restaurant_id, source_date, calendar_date, hour, fold)
    do update set net = excluded.net, captured_at = excluded.captured_at;
  if not exists (
    select 1 from public.sales_hourly
    where restaurant_id = 'R001' and source_date = '2035-01-03'
      and calendar_date = '2035-01-03' and hour = 8 and fold = 0
      and net = 31.00 and captured_at = '2035-01-03T09:01:00Z'
  ) then
    raise exception 'sales_hourly ON CONFLICT no actualizó la fila';
  end if;

  insert into public.sales_daily_totals (
    restaurant_id, sales_date, net, hourly_net_sum, captured_at, source, quality
  ) values (
    'R001', '2035-01-03', 30.00, 30.00, '2035-01-03T09:00:00Z', 'live', 'clean'
  );
  insert into public.sales_daily_totals (
    restaurant_id, sales_date, net, hourly_net_sum, captured_at, source, quality
  ) values (
    'R001', '2035-01-03', 31.00, 31.00, '2035-01-03T09:01:00Z', 'live', 'clean'
  ) on conflict (restaurant_id, sales_date)
    do update set
      net = excluded.net,
      hourly_net_sum = excluded.hourly_net_sum,
      captured_at = excluded.captured_at;
  if not exists (
    select 1 from public.sales_daily_totals
    where restaurant_id = 'R001' and sales_date = '2035-01-03'
      and net = 31.00 and hourly_net_sum = 31.00
      and captured_at = '2035-01-03T09:01:00Z'
  ) then
    raise exception 'sales_daily_totals ON CONFLICT no actualizó la fila';
  end if;

  delete from public.sales_daily_totals
  where restaurant_id = 'R001' and sales_date = '2035-01-03';
  delete from public.sales_hourly
  where restaurant_id = 'R001' and source_date = '2035-01-03';
  if exists (
    select 1 from public.sales_hourly
    where restaurant_id = 'R001' and source_date = '2035-01-03'
  ) or exists (
    select 1 from public.sales_daily_totals
    where restaurant_id = 'R001' and sales_date = '2035-01-03'
  ) then
    raise exception 'el rol de venta no pudo retirar sus filas de snapshot';
  end if;

  insert into public.ingest_runs (
    restaurant_id, source, started_at, status
  ) values ('R001', 'sales', '2035-01-03T08:00:00Z', 'running')
  returning id into run_id;
  update public.ingest_runs
  set finished_at = '2035-01-03T08:01:00Z', status = 'ok'
  where id = run_id;
  if not exists (
    select 1 from public.ingest_runs where id = run_id and status = 'ok'
  ) then
    raise exception 'ingest_runs UPDATE no cerró el ciclo de venta';
  end if;
  perform set_config('tests.sales_upserts', 'ok', true);

  begin
    insert into public.workforce_projection_hourly (
      restaurant_id, sales_date, hour, sales, guest_counts, expected_hours, fetched_at
    ) values (
      'R001', '2035-01-03', 8, 30.00, 3, array[8]::smallint[],
      '2035-01-03T09:00:00Z'
    );
    perform set_config('tests.sales_cross_table', 'unexpected-success', true);
  exception when insufficient_privilege then
    perform set_config('tests.sales_cross_table', sqlstate, true);
  end;
  begin
    insert into public.ingest_runs (
      restaurant_id, source, started_at, status
    ) values ('R001', 'workforce', '2035-01-03T08:00:00Z', 'running');
    perform set_config('tests.sales_cross_run', 'unexpected-success', true);
  exception when insufficient_privilege then
    perform set_config('tests.sales_cross_run', sqlstate, true);
  end;
end;
$$;
reset role;

select is(
  current_setting('tests.sales_upserts'),
  'ok',
  'venta ejecuta ON CONFLICT real en hourly y daily, SELECT/DELETE y cierre de run'
);
select is(
  current_setting('tests.sales_cross_table'),
  '42501',
  'venta no escribe tablas de personal'
);
select is(
  current_setting('tests.sales_cross_run'),
  '42501',
  'venta no simula runs de personal'
);

set local role workforce_ingest_worker;
do $$
declare
  run_id bigint;
begin
  insert into public.workforce_projection_hourly (
    restaurant_id, sales_date, hour, sales, guest_counts, expected_hours, fetched_at
  ) values (
    'R001', '2035-01-03', 8, 30.00, 3, array[8]::smallint[],
    '2035-01-03T09:00:00Z'
  );
  insert into public.workforce_projection_hourly (
    restaurant_id, sales_date, hour, sales, guest_counts, expected_hours, fetched_at
  ) values (
    'R001', '2035-01-03', 8, 31.00, 4, array[8]::smallint[],
    '2035-01-03T09:01:00Z'
  )
  on conflict (restaurant_id, sales_date, hour)
    do update set
      sales = excluded.sales,
      guest_counts = excluded.guest_counts,
      expected_hours = excluded.expected_hours,
      fetched_at = excluded.fetched_at;
  if not exists (
    select 1 from public.workforce_projection_hourly
    where restaurant_id = 'R001' and sales_date = '2035-01-03' and hour = 8
      and sales = 31.00 and guest_counts = 4
      and expected_hours = array[8]::smallint[]
      and fetched_at = '2035-01-03T09:01:00Z'
  ) then
    raise exception 'workforce_projection_hourly ON CONFLICT no actualizó la fila';
  end if;

  insert into public.workforce_staffing_hourly (
    restaurant_id, sales_date, hour, assigned_count, assigned_minutes,
    expected_hours, fetched_at
  ) values (
    'R001', '2035-01-03', 8, 3, 180, array[8]::smallint[],
    '2035-01-03T09:00:00Z'
  );
  insert into public.workforce_staffing_hourly (
    restaurant_id, sales_date, hour, assigned_count, assigned_minutes,
    expected_hours, fetched_at
  ) values (
    'R001', '2035-01-03', 8, 4, 240, array[8]::smallint[],
    '2035-01-03T09:01:00Z'
  )
  on conflict (restaurant_id, sales_date, hour)
    do update set
      assigned_count = excluded.assigned_count,
      assigned_minutes = excluded.assigned_minutes,
      expected_hours = excluded.expected_hours,
      fetched_at = excluded.fetched_at;
  if not exists (
    select 1 from public.workforce_staffing_hourly
    where restaurant_id = 'R001' and sales_date = '2035-01-03' and hour = 8
      and assigned_count = 4 and assigned_minutes = 240
      and expected_hours = array[8]::smallint[]
      and fetched_at = '2035-01-03T09:01:00Z'
  ) then
    raise exception 'workforce_staffing_hourly ON CONFLICT no actualizó la fila';
  end if;

  begin
    delete from public.workforce_projection_hourly
    where restaurant_id = 'R001' and sales_date = '2035-01-03';
    perform set_config('tests.workforce_projection_delete', 'unexpected-success', true);
  exception when insufficient_privilege then
    perform set_config('tests.workforce_projection_delete', sqlstate, true);
  end;
  begin
    delete from public.workforce_staffing_hourly
    where restaurant_id = 'R001' and sales_date = '2035-01-03';
    perform set_config('tests.workforce_staffing_delete', 'unexpected-success', true);
  exception when insufficient_privilege then
    perform set_config('tests.workforce_staffing_delete', sqlstate, true);
  end;
  if current_setting('tests.workforce_projection_delete', true) <> '42501'
     or current_setting('tests.workforce_staffing_delete', true) <> '42501' then
    raise exception 'el rol de personal conserva permiso DELETE';
  end if;

  insert into public.ingest_runs (
    restaurant_id, source, started_at, status
  ) values ('R001', 'workforce', '2035-01-03T08:00:00Z', 'running')
  returning id into run_id;
  update public.ingest_runs
  set finished_at = '2035-01-03T08:01:00Z', status = 'ok'
  where id = run_id;
  if not exists (
    select 1 from public.ingest_runs where id = run_id and status = 'ok'
  ) then
    raise exception 'ingest_runs UPDATE no cerró el ciclo de personal';
  end if;
  perform set_config('tests.workforce_upserts', 'ok', true);

  begin
    insert into public.sales_hourly (
      restaurant_id, source_date, sales_date, calendar_date, hour, fold,
      net, captured_at, source
    ) values (
      'R001', '2035-01-03', '2035-01-03', '2035-01-03', 9, 0,
      40.00, '2035-01-03T10:00:00Z', 'live'
    );
    perform set_config('tests.workforce_cross_table', 'unexpected-success', true);
  exception when insufficient_privilege then
    perform set_config('tests.workforce_cross_table', sqlstate, true);
  end;
  begin
    insert into public.ingest_runs (
      restaurant_id, source, started_at, status
    ) values ('R001', 'sales', '2035-01-03T08:00:00Z', 'running');
    perform set_config('tests.workforce_cross_run', 'unexpected-success', true);
  exception when insufficient_privilege then
    perform set_config('tests.workforce_cross_run', sqlstate, true);
  end;
end;
$$;
reset role;

select is(
  current_setting('tests.workforce_upserts'),
  'ok',
  'personal ejecuta ON CONFLICT en projection y staffing, DELETE rechazado y cierre de run'
);
select is(
  current_setting('tests.workforce_cross_table'),
  '42501',
  'personal no escribe tablas de venta'
);
select is(
  current_setting('tests.workforce_cross_run'),
  '42501',
  'personal no simula runs de venta'
);

select * from finish();
rollback;
