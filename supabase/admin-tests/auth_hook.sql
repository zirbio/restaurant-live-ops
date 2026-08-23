begin;

create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;

select plan(2);

insert into private.allowed_email (email)
values ('invited@example.test')
on conflict (email) do nothing;

-- Este archivo se ejecuta obligatoriamente con la conexión local de
-- supabase_admin. Si no puede asumir el rol reservado, el gate debe fallar.
set local role supabase_auth_admin;

select set_config(
  'tests.hook_allowed',
  private.restrict_signup_to_allowlist(
    '{"user":{"email":" Invited@Example.Test "}}'::jsonb
  )::text,
  true
);
select set_config(
  'tests.hook_denied',
  private.restrict_signup_to_allowlist(
    '{"user":{"email":"unknown@example.test"}}'::jsonb
  ) #>> '{error,http_code}',
  true
);

reset role;

select is(
  current_setting('tests.hook_allowed'),
  '{}',
  'supabase_auth_admin ejecuta el hook y admite una dirección incluida'
);

select is(
  current_setting('tests.hook_denied'),
  '403',
  'supabase_auth_admin ejecuta el hook y rechaza una dirección ausente'
);

select * from finish();
rollback;
