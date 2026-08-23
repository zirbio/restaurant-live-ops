import os
import stat
from pathlib import Path
from subprocess import CompletedProcess, run

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RELEASE_GATE = REPOSITORY_ROOT / "scripts" / "verify_public_release.sh"
SUPABASE_GATE = REPOSITORY_ROOT / "scripts" / "test-supabase-local.sh"


def _install_command_stub(bin_dir: Path, command: str) -> None:
    stub = bin_dir / command
    stub.write_text(
        """#!/bin/bash
set -eu

actual="$0"
actual="${actual##*/}"
for argument in "$@"; do
  actual="$actual $argument"
done

printf '%s\\t%s\\n' "$PWD" "$actual" >> "$RELEASE_GATE_LOG"
if [[ "${RELEASE_GATE_FAIL_COMMAND:-}" == "$actual" ]]; then
  exit 93
fi
"""
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)


def _install_supabase_stub(bin_dir: Path) -> None:
    stub = bin_dir / "supabase"
    stub.write_text(
        """#!/bin/bash
set -eu

actual="supabase"
for argument in "$@"; do
  actual="$actual $argument"
done
printf '%s\\t%s\\n' "$PWD" "$actual" >> "$RELEASE_GATE_LOG"

if [[ "$*" == "status -o env" ]]; then
  printf '%s\\n' \\
    "DB_URL='postgresql://postgres:<PASSWORD>@127.0.0.1:54322/postgres'" \\
    "API_URL='http://127.0.0.1:54321'" \\
    "ANON_KEY='<PASSWORD>'" \\
    "SERVICE_ROLE_KEY='<PASSWORD>'"
fi
"""
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)


def _run_gate(
    tmp_path: Path,
    *arguments: str,
    approvals: tuple[bool, bool] = (False, False),
    fail_command: str | None = None,
) -> tuple[CompletedProcess[str], list[tuple[str, str]]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("bash", "docker", "gitleaks", "npm", "pre-commit", "supabase", "uv"):
        _install_command_stub(bin_dir, command)

    log_path = tmp_path / "commands.log"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "RELEASE_GATE_LOG": str(log_path),
        }
    )
    environment.pop("CONNECTOR_REDISTRIBUTION_APPROVED", None)
    environment.pop("PUBLIC_LICENSE_APPROVED", None)
    if approvals[0]:
        environment["CONNECTOR_REDISTRIBUTION_APPROVED"] = "true"
    if approvals[1]:
        environment["PUBLIC_LICENSE_APPROVED"] = "true"
    if fail_command is not None:
        environment["RELEASE_GATE_FAIL_COMMAND"] = fail_command

    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    result = run(
        ["/bin/bash", str(RELEASE_GATE), *arguments],
        cwd=unrelated_cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    commands: list[tuple[str, str]] = []
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            working_directory, command = line.split("\t", 1)
            commands.append((working_directory, command))
    return result, commands


def _expected_commands() -> list[tuple[str, str]]:
    root = str(REPOSITORY_ROOT)
    return [
        (root, "pre-commit run --all-files"),
        (f"{root}/app", "npm run lint"),
        (f"{root}/app", "npm run typecheck"),
        (f"{root}/app", "npm test"),
        (f"{root}/app", "npm run build"),
        (f"{root}/app", "npm audit --audit-level=high"),
        (f"{root}/app", "npm audit --omit=dev --audit-level=high"),
        (f"{root}/worker", "uv run --python 3.12 ruff check ."),
        (f"{root}/worker", "uv run --python 3.12 ruff format --check ."),
        (f"{root}/worker", "uv run --python 3.12 mypy"),
        (f"{root}/worker", "uv run --python 3.12 pytest -q"),
        (
            f"{root}/worker",
            "docker build --no-cache --tag restaurant-live-ops-worker:release .",
        ),
        (root, "supabase db reset --local"),
        (root, "bash scripts/test-supabase-local.sh"),
        (root, "supabase db advisors --local --type security"),
        (root, "gitleaks dir ."),
        (
            root,
            "uv run --python 3.12 --project worker python scripts/check_repository_hygiene.py .",
        ),
        (
            root,
            "uv run --python 3.12 --project worker python "
            "scripts/check_repository_hygiene.py --git-archive .",
        ),
    ]


def test_private_mode_is_default_and_runs_every_gate_from_the_repository_root(
    tmp_path: Path,
) -> None:
    result, commands = _run_gate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert commands == _expected_commands()


@pytest.mark.parametrize(
    "approvals,missing_approval",
    [
        ((False, False), "CONNECTOR_REDISTRIBUTION_APPROVED"),
        ((True, False), "PUBLIC_LICENSE_APPROVED"),
        ((False, True), "CONNECTOR_REDISTRIBUTION_APPROVED"),
    ],
)
def test_public_mode_fails_closed_until_both_approvals_are_explicit(
    tmp_path: Path,
    approvals: tuple[bool, bool],
    missing_approval: str,
) -> None:
    result, commands = _run_gate(tmp_path, "public", approvals=approvals)

    assert result.returncode != 0
    assert missing_approval in result.stderr
    assert commands == []


def test_public_mode_runs_the_same_gates_after_both_explicit_approvals(tmp_path: Path) -> None:
    result, commands = _run_gate(tmp_path, "public", approvals=(True, True))

    assert result.returncode == 0, result.stderr
    assert commands == _expected_commands()


@pytest.mark.parametrize(
    "failed_command",
    [
        "npm audit --omit=dev --audit-level=high",
        "docker build --no-cache --tag restaurant-live-ops-worker:release .",
        "supabase db reset --local",
        "gitleaks dir .",
    ],
)
def test_infrastructure_or_security_failure_stops_the_release_gate(
    tmp_path: Path, failed_command: str
) -> None:
    result, commands = _run_gate(tmp_path, fail_command=failed_command)

    expected = _expected_commands()
    failure_index = [command for _, command in expected].index(failed_command)
    assert result.returncode == 93
    assert commands == expected[: failure_index + 1]


def test_rejects_an_unknown_release_mode_before_running_tools(tmp_path: Path) -> None:
    result, commands = _run_gate(tmp_path, "preview")

    assert result.returncode != 0
    assert "private|public" in result.stderr
    assert commands == []


def test_supabase_gate_runs_worker_integration_with_python_312(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("npm", "uv"):
        _install_command_stub(bin_dir, command)
    _install_supabase_stub(bin_dir)

    log_path = tmp_path / "commands.log"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "RELEASE_GATE_LOG": str(log_path),
        }
    )
    result = run(
        ["/bin/bash", str(SUPABASE_GATE)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    root = str(REPOSITORY_ROOT)
    commands = [tuple(line.split("\t", 1)) for line in log_path.read_text().splitlines()]
    assert commands == [
        (root, "supabase status -o env"),
        (root, "supabase test db supabase/tests/rls.sql --local"),
        (
            root,
            "supabase test db supabase/admin-tests --db-url "
            "postgresql://supabase_admin:<PASSWORD>@127.0.0.1:54322/postgres",
        ),
        (
            root,
            "uv run --python 3.12 --project worker pytest -q "
            "worker/tests/test_db_local_integration.py",
        ),
        (root, "npm --prefix app test -- tests/useDayLocalIntegration.test.ts"),
    ]
