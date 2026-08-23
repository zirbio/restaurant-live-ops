#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

status_env="$(supabase status -o env)"
selected_env="$(
  printf '%s\n' "$status_env" |
    awk -F= '$1 == "DB_URL" || $1 == "API_URL" || $1 == "ANON_KEY" || $1 == "SERVICE_ROLE_KEY"'
)"
unset status_env

if [[ -z "$selected_env" ]]; then
  echo "No se pudieron derivar las variables de la instancia Supabase local." >&2
  exit 1
fi

eval "$selected_env"
unset selected_env

for variable in DB_URL API_URL ANON_KEY SERVICE_ROLE_KEY; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Falta $variable en el estado de Supabase local." >&2
    exit 1
  fi
done

if [[ "$DB_URL" != postgresql://postgres:* ]]; then
  echo "La conexión local no tiene el formato esperado para el runner portable." >&2
  exit 1
fi

admin_db_url="${DB_URL/postgres:/supabase_admin:}"
trap 'unset DB_URL API_URL ANON_KEY SERVICE_ROLE_KEY admin_db_url' EXIT

supabase test db supabase/tests/rls.sql --local
supabase test db supabase/admin-tests --db-url "$admin_db_url"
LOCAL_SUPABASE_DB_URL="$DB_URL" \
  uv run --python 3.12 --project worker pytest -q worker/tests/test_db_local_integration.py
LOCAL_SUPABASE_URL="$API_URL" \
LOCAL_SUPABASE_ANON_KEY="$ANON_KEY" \
LOCAL_SUPABASE_SERVICE_ROLE_KEY="$SERVICE_ROLE_KEY" \
LOCAL_SUPABASE_DB_URL="$DB_URL" \
  npm --prefix app test -- tests/useDayLocalIntegration.test.ts
