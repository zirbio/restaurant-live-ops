-- Esquema público independiente para datos operativos agregados.
-- Las fechas de negocio llegan ya resueltas en Europe/Madrid desde el worker;
-- los instantes se guardan con zona y ninguna tabla contiene PII de empleados.

create schema private;
revoke all on schema private from public;

create role sales_ingest_worker
  nologin nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
create role workforce_ingest_worker
  nologin nosuperuser nocreatedb nocreaterole noinherit nobypassrls;

create table public.restaurants (
  id                text primary key,
  name              text not null,
  sort_order        smallint generated always as identity unique,
  has_drive_through boolean not null default false
);

create table public.app_user_access (
  user_id       uuid not null references auth.users(id) on delete cascade,
  restaurant_id text not null references public.restaurants(id) on delete cascade,
  created_at    timestamptz not null default now(),
  primary key (user_id, restaurant_id)
);

create index app_user_access_restaurant_id_idx
  on public.app_user_access (restaurant_id);

create table private.allowed_email (
  email      text primary key,
  created_at timestamptz not null default now(),
  constraint allowed_email_normalized
    check (email <> '' and email = lower(trim(email)))
);

create table public.sales_hourly (
  restaurant_id text not null references public.restaurants(id) on delete cascade,
  source_date    date not null,
  sales_date     date not null,
  calendar_date  date not null,
  hour           smallint not null check (hour between 0 and 23),
  fold           smallint not null check (fold in (0, 1)),
  net            numeric(12, 2),
  gross          numeric(12, 2),
  gc             integer,
  drive_through_net   numeric(12, 2),
  drive_through_gross numeric(12, 2),
  drive_through_cars  integer,
  delivery_net        numeric(12, 2),
  delivery_gross      numeric(12, 2),
  delivery_count      integer,
  kvs            numeric(8, 2),
  r2p            numeric(8, 2),
  oepe           numeric(8, 2),
  captured_at    timestamptz not null,
  source         text not null check (source in ('live', 'backfill', 'import')),
  primary key (restaurant_id, source_date, calendar_date, hour, fold)
);

create index sales_hourly_sales_date_idx
  on public.sales_hourly (sales_date, restaurant_id, hour, calendar_date, fold);

create index sales_hourly_source_snapshot_idx
  on public.sales_hourly (restaurant_id, source_date, sales_date);

create table public.sales_daily_totals (
  restaurant_id  text not null references public.restaurants(id) on delete cascade,
  sales_date      date not null,
  net             numeric(12, 2),
  gross           numeric(12, 2),
  gc              integer,
  drive_through_net numeric(12, 2),
  drive_through_gross numeric(12, 2),
  drive_through_cars integer,
  delivery_net    numeric(12, 2),
  delivery_gross  numeric(12, 2),
  delivery_count  integer,
  kvs             numeric(8, 2),
  r2p             numeric(8, 2),
  oepe            numeric(8, 2),
  hourly_net_sum  numeric(12, 2) not null,
  totals_mismatch numeric(12, 2),
  header_date     date,
  captured_at     timestamptz not null,
  source          text not null check (source in ('live', 'backfill', 'import')),
  quality         text not null check (quality in ('clean', 'rebucketed')),
  primary key (restaurant_id, sales_date)
);

create index sales_daily_totals_sales_date_idx
  on public.sales_daily_totals (sales_date, restaurant_id);

create table public.workforce_projection_hourly (
  restaurant_id text not null references public.restaurants(id) on delete cascade,
  sales_date     date not null,
  hour           smallint not null check (hour between 0 and 23),
  sales          numeric(12, 2) not null,
  guest_counts   numeric(12, 2) not null,
  expected_hours smallint[] not null,
  fetched_at     timestamptz not null,
  constraint workforce_projection_expected_hours_valid check (
    cardinality(expected_hours) between 1 and 24
    and array_position(expected_hours, null) is null
    and expected_hours <@ array[
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
      12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23
    ]::smallint[]
  ),
  primary key (restaurant_id, sales_date, hour)
);

create index workforce_projection_hourly_sales_date_idx
  on public.workforce_projection_hourly (sales_date, restaurant_id, hour);

create table public.workforce_staffing_hourly (
  restaurant_id        text not null references public.restaurants(id) on delete cascade,
  sales_date            date not null,
  hour                  smallint not null check (hour between 0 and 23),
  clocked_count         integer,
  assigned_count        integer not null,
  clocked_minutes       integer,
  assigned_minutes      integer not null,
  open_anomalies        integer not null default 0,
  crew_clocked_count    integer,
  crew_assigned_count   integer,
  crew_clocked_minutes  integer,
  crew_assigned_minutes integer,
  crew_open_anomalies   integer,
  expected_hours        smallint[] not null,
  fetched_at            timestamptz not null,
  constraint workforce_staffing_counts_nonnegative check (
    (clocked_count is null or clocked_count >= 0)
    and assigned_count >= 0
    and (clocked_minutes is null or clocked_minutes >= 0)
    and assigned_minutes >= 0
    and open_anomalies >= 0
    and (crew_clocked_count is null or crew_clocked_count >= 0)
    and (crew_assigned_count is null or crew_assigned_count >= 0)
    and (crew_clocked_minutes is null or crew_clocked_minutes >= 0)
    and (crew_assigned_minutes is null or crew_assigned_minutes >= 0)
    and (crew_open_anomalies is null or crew_open_anomalies >= 0)
  ),
  constraint workforce_staffing_expected_hours_valid check (
    cardinality(expected_hours) between 1 and 24
    and array_position(expected_hours, null) is null
    and expected_hours <@ array[
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
      12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23
    ]::smallint[]
  ),
  primary key (restaurant_id, sales_date, hour)
);

create index workforce_staffing_hourly_sales_date_idx
  on public.workforce_staffing_hourly (sales_date, restaurant_id, hour);

create table public.ingest_runs (
  id            bigint generated always as identity primary key,
  restaurant_id text not null references public.restaurants(id) on delete cascade,
  source        text not null
    check (source in ('sales', 'sales_backfill', 'workforce', 'staffing')),
  started_at    timestamptz not null,
  finished_at   timestamptz,
  status        text not null check (status in ('running', 'ok', 'error')),
  rows_written  integer not null default 0 check (rows_written >= 0),
  error         text,
  constraint ingest_runs_state_coherent check (
    (status = 'running' and finished_at is null and error is null)
    or (status = 'ok' and finished_at is not null and error is null)
    or (
      status = 'error'
      and finished_at is not null
      and nullif(btrim(error), '') is not null
    )
  ),
  constraint ingest_runs_finished_after_started check (
    finished_at is null or finished_at >= started_at
  )
);

create index ingest_runs_restaurant_source_started_idx
  on public.ingest_runs (restaurant_id, source, started_at desc, id desc);

create table public.monthly_snapshots (
  restaurant_id text not null references public.restaurants(id) on delete cascade,
  year           smallint not null check (year between 2000 and 9999),
  month          smallint not null check (month between 1 and 12),
  covers_through date not null,
  net_sales      numeric(15, 2) not null,
  labor_cost     numeric(15, 2) not null,
  captured_at    timestamptz not null,
  constraint monthly_snapshots_covers_period check (
    extract(year from covers_through)::integer = year
    and extract(month from covers_through)::integer = month
  ),
  primary key (restaurant_id, year, month, covers_through)
);

create index monthly_snapshots_period_idx
  on public.monthly_snapshots (year, month, covers_through, restaurant_id);

-- El predicado se ejecuta con los privilegios del usuario. app_user_access
-- aplica su propia política simple, por lo que no necesita saltarse RLS.
create function private.can_read_restaurant(target text)
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select exists (
    select 1
    from public.app_user_access access
    where access.user_id = (select auth.uid())
      and access.restaurant_id = target
  );
$$;

revoke execute on function private.can_read_restaurant(text)
  from public, anon, authenticated, service_role;
grant usage on schema private to authenticated;
grant execute on function private.can_read_restaurant(text) to authenticated;

-- Hook before-user-created: la tabla sigue inaccesible incluso para Auth; el
-- único acceso es esta función con search_path vacío y payload jsonb explícito.
create function private.restrict_signup_to_allowlist(event jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  candidate_email text := lower(trim(coalesce(event -> 'user' ->> 'email', '')));
begin
  if candidate_email <> '' and exists (
    select 1
    from private.allowed_email allowed
    where allowed.email = candidate_email
  ) then
    return '{}'::jsonb;
  end if;

  return jsonb_build_object(
    'error',
    jsonb_build_object(
      'http_code', 403,
      'message', 'Esta dirección no está autorizada.'
    )
  );
end;
$$;

revoke execute on function private.restrict_signup_to_allowlist(jsonb)
  from public, anon, authenticated, service_role,
       sales_ingest_worker, workforce_ingest_worker;
grant usage on schema private to supabase_auth_admin;
grant execute on function private.restrict_signup_to_allowlist(jsonb)
  to supabase_auth_admin;

revoke all on table private.allowed_email
  from public, anon, authenticated, service_role, supabase_auth_admin,
       sales_ingest_worker, workforce_ingest_worker;

alter table public.restaurants enable row level security;
alter table public.app_user_access enable row level security;
alter table public.sales_hourly enable row level security;
alter table public.sales_daily_totals enable row level security;
alter table public.workforce_projection_hourly enable row level security;
alter table public.workforce_staffing_hourly enable row level security;
alter table public.ingest_runs enable row level security;
alter table public.monthly_snapshots enable row level security;

create policy authenticated_reads_own_access
  on public.app_user_access
  for select
  to authenticated
  using (user_id = (select auth.uid()));

create policy authenticated_reads_own_restaurants
  on public.restaurants
  for select
  to authenticated
  using (private.can_read_restaurant(id));

create policy authenticated_reads_own_sales_hourly
  on public.sales_hourly
  for select
  to authenticated
  using (private.can_read_restaurant(restaurant_id));

create policy authenticated_reads_own_sales_daily_totals
  on public.sales_daily_totals
  for select
  to authenticated
  using (private.can_read_restaurant(restaurant_id));

create policy authenticated_reads_own_workforce_projection
  on public.workforce_projection_hourly
  for select
  to authenticated
  using (private.can_read_restaurant(restaurant_id));

create policy authenticated_reads_own_workforce_staffing
  on public.workforce_staffing_hourly
  for select
  to authenticated
  using (private.can_read_restaurant(restaurant_id));

create policy authenticated_reads_own_ingest_runs
  on public.ingest_runs
  for select
  to authenticated
  using (private.can_read_restaurant(restaurant_id));

create policy authenticated_reads_own_monthly_snapshots
  on public.monthly_snapshots
  for select
  to authenticated
  using (private.can_read_restaurant(restaurant_id));

create policy sales_worker_reads_hourly
  on public.sales_hourly for select to sales_ingest_worker using (true);
create policy sales_worker_inserts_hourly
  on public.sales_hourly for insert to sales_ingest_worker with check (true);
create policy sales_worker_updates_hourly
  on public.sales_hourly for update to sales_ingest_worker
  using (true) with check (true);
create policy sales_worker_deletes_hourly
  on public.sales_hourly for delete to sales_ingest_worker using (true);

create policy sales_worker_reads_daily_totals
  on public.sales_daily_totals for select to sales_ingest_worker using (true);
create policy sales_worker_inserts_daily_totals
  on public.sales_daily_totals for insert to sales_ingest_worker with check (true);
create policy sales_worker_updates_daily_totals
  on public.sales_daily_totals for update to sales_ingest_worker
  using (true) with check (true);
create policy sales_worker_deletes_daily_totals
  on public.sales_daily_totals for delete to sales_ingest_worker using (true);

create policy workforce_worker_reads_projection
  on public.workforce_projection_hourly for select to workforce_ingest_worker using (true);
create policy workforce_worker_inserts_projection
  on public.workforce_projection_hourly for insert to workforce_ingest_worker with check (true);
create policy workforce_worker_updates_projection
  on public.workforce_projection_hourly for update to workforce_ingest_worker
  using (true) with check (true);

create policy workforce_worker_reads_staffing
  on public.workforce_staffing_hourly for select to workforce_ingest_worker using (true);
create policy workforce_worker_inserts_staffing
  on public.workforce_staffing_hourly for insert to workforce_ingest_worker with check (true);
create policy workforce_worker_updates_staffing
  on public.workforce_staffing_hourly for update to workforce_ingest_worker
  using (true) with check (true);

create policy sales_worker_reads_runs
  on public.ingest_runs for select to sales_ingest_worker
  using (source in ('sales', 'sales_backfill'));
create policy sales_worker_inserts_runs
  on public.ingest_runs for insert to sales_ingest_worker
  with check (source in ('sales', 'sales_backfill'));
create policy sales_worker_updates_runs
  on public.ingest_runs for update to sales_ingest_worker
  using (source in ('sales', 'sales_backfill'))
  with check (source in ('sales', 'sales_backfill'));

create policy workforce_worker_reads_runs
  on public.ingest_runs for select to workforce_ingest_worker
  using (source in ('workforce', 'staffing'));
create policy workforce_worker_inserts_runs
  on public.ingest_runs for insert to workforce_ingest_worker
  with check (source in ('workforce', 'staffing'));
create policy workforce_worker_updates_runs
  on public.ingest_runs for update to workforce_ingest_worker
  using (source in ('workforce', 'staffing'))
  with check (source in ('workforce', 'staffing'));

-- Grants de Data API explícitos. RLS decide filas; estos grants deciden qué
-- objetos son alcanzables. anon no recibe ningún objeto del contrato.
revoke all on table
  public.restaurants,
  public.app_user_access,
  public.sales_hourly,
  public.sales_daily_totals,
  public.workforce_projection_hourly,
  public.workforce_staffing_hourly,
  public.ingest_runs,
  public.monthly_snapshots
from public, anon, authenticated, service_role,
     sales_ingest_worker, workforce_ingest_worker;

grant usage on schema public
  to authenticated, sales_ingest_worker, workforce_ingest_worker;

grant select on table
  public.restaurants,
  public.app_user_access,
  public.sales_hourly,
  public.sales_daily_totals,
  public.workforce_projection_hourly,
  public.workforce_staffing_hourly,
  public.ingest_runs,
  public.monthly_snapshots
to authenticated;

grant select, insert, update, delete on table
  public.sales_hourly,
  public.sales_daily_totals
to sales_ingest_worker;
grant select, insert, update on table public.ingest_runs
  to sales_ingest_worker;

grant select, insert, update on table
  public.workforce_projection_hourly,
  public.workforce_staffing_hourly
to workforce_ingest_worker;
grant select, insert, update on table public.ingest_runs
  to workforce_ingest_worker;

revoke all on sequence public.ingest_runs_id_seq
  from public, anon, authenticated, service_role,
       sales_ingest_worker, workforce_ingest_worker;
grant usage on sequence public.ingest_runs_id_seq
  to sales_ingest_worker, workforce_ingest_worker;

comment on table public.app_user_access is
  'Asignaciones explícitas de usuarios autenticados a restaurantes; sin acceso global implícito.';
comment on table public.ingest_runs is
  'Ciclos de ingesta por restaurante: los fallos y la frescura respetan el mismo aislamiento RLS.';
comment on table public.monthly_snapshots is
  'Contrato opcional y de solo lectura para adaptadores mensuales externos.';
comment on function private.can_read_restaurant(text) is
  'Predicado SECURITY INVOKER usado por RLS; consulta únicamente las filas propias de app_user_access.';
comment on function private.restrict_signup_to_allowlist(jsonb) is
  'Hook before-user-created privado; admite solo correos normalizados presentes en allowed_email.';
