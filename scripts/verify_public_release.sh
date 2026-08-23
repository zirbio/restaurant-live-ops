#!/usr/bin/env bash

set -euo pipefail

script_directory="${BASH_SOURCE[0]%/*}"
repository_root="$(cd -P -- "$script_directory/.." && pwd)"
release_mode="${1:-private}"

if [[ $# -gt 1 || ("$release_mode" != "private" && "$release_mode" != "public") ]]; then
  printf 'Uso: scripts/verify_public_release.sh [private|public]\n' >&2
  exit 2
fi

if [[ "$release_mode" == "public" ]]; then
  if [[ "${CONNECTOR_REDISTRIBUTION_APPROVED:-}" != "true" ]]; then
    printf '%s\n' \
      'Bloqueo: CONNECTOR_REDISTRIBUTION_APPROVED=true requiere aprobación explícita.' >&2
    exit 3
  fi
  if [[ "${PUBLIC_LICENSE_APPROVED:-}" != "true" ]]; then
    printf '%s\n' 'Bloqueo: PUBLIC_LICENSE_APPROVED=true requiere aprobación explícita.' >&2
    exit 3
  fi
fi

cd "$repository_root"
pre-commit run --all-files

cd "$repository_root/app"
npm run lint
npm run typecheck
npm test
npm run build
npm audit --audit-level=high
npm audit --omit=dev --audit-level=high

cd "$repository_root/worker"
uv run --python 3.12 ruff check .
uv run --python 3.12 ruff format --check .
uv run --python 3.12 mypy
uv run --python 3.12 pytest -q
docker build --no-cache --tag restaurant-live-ops-worker:release .

cd "$repository_root"
supabase db reset --local
bash scripts/test-supabase-local.sh
supabase db advisors --local --type security
gitleaks dir .
uv run --python 3.12 --project worker python scripts/check_repository_hygiene.py .
uv run --python 3.12 --project worker python \
  scripts/check_repository_hygiene.py --git-archive .

printf 'Gate técnico superado en modo %s. Este resultado no cambia la visibilidad.\n' \
  "$release_mode"
