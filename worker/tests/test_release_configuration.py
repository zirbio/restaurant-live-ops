import re
import shlex
from pathlib import Path
from subprocess import run

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _workflow() -> dict[str, object]:
    loaded = yaml.safe_load((REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    assert isinstance(loaded, dict)
    return loaded


def _pre_commit_config() -> dict[str, object]:
    loaded = yaml.safe_load((REPOSITORY_ROOT / ".pre-commit-config.yaml").read_text())
    assert isinstance(loaded, dict)
    return loaded


def test_ci_has_four_isolated_jobs_with_minimum_permissions_and_pinned_actions() -> None:
    workflow = _workflow()

    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"worker", "app", "supabase", "security"}

    for job in jobs.values():
        assert isinstance(job, dict)
        steps = job["steps"]
        assert isinstance(steps, list)
        for step in steps:
            assert isinstance(step, dict)
            action = step.get("uses")
            if action is None:
                continue
            _, revision = action.rsplit("@", 1)
            assert COMMIT_SHA.fullmatch(revision), action


def test_ci_runs_local_supabase_security_and_release_mechanics_without_private_inputs() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)

    worker_steps = jobs["worker"]["steps"]
    app_steps = jobs["app"]["steps"]
    supabase_steps = jobs["supabase"]["steps"]
    security_steps = jobs["security"]["steps"]

    assert {step.get("run") for step in worker_steps} >= {
        "uv run --python 3.12 ruff check .",
        "uv run --python 3.12 ruff format --check .",
        "uv run --python 3.12 mypy",
        "uv run --python 3.12 pytest -q",
        "docker build --no-cache --tag restaurant-live-ops-worker:ci .",
    }
    assert {step.get("run") for step in app_steps} >= {
        "npm run lint",
        "npm run typecheck",
        "npm test",
        "npm run build",
        "npm audit --audit-level=high",
        "npm audit --omit=dev --audit-level=high",
    }
    assert {step.get("run") for step in supabase_steps} >= {
        "supabase start",
        "supabase db reset --local",
        "bash scripts/test-supabase-local.sh",
        "supabase db advisors --local --type security",
    }
    assert not any("project-ref" in str(step) for step in supabase_steps)
    for job_steps in (worker_steps, supabase_steps, security_steps):
        setup_python = [
            step for step in job_steps if step.get("uses", "").startswith("actions/setup-python@")
        ]
        assert len(setup_python) == 1
        assert setup_python[0].get("with", {}).get("python-version") == "3.12"
    assert any(step.get("with", {}).get("fetch-depth") == 0 for step in security_steps)
    assert any("gitleaks/gitleaks-action@" in step.get("uses", "") for step in security_steps)
    hygiene_commands = {
        "uv run --python 3.12 --project worker python scripts/check_repository_hygiene.py .",
        "uv run --python 3.12 --project worker python "
        "scripts/check_repository_hygiene.py --git-archive .",
    }
    assert {step.get("run") for step in security_steps} >= hygiene_commands


def test_pre_commit_config_is_valid_pinned_and_does_not_recurse_into_release_gate() -> None:
    result = run(
        ["pre-commit", "validate-config", ".pre-commit-config.yaml"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    config = _pre_commit_config()
    assert config["minimum_pre_commit_version"] == "4.6.1"
    assert config["default_install_hook_types"] == ["pre-commit", "pre-push"]
    repositories = config["repos"]
    assert isinstance(repositories, list)
    external_revisions = [repository["rev"] for repository in repositories if "rev" in repository]
    assert external_revisions
    assert all(COMMIT_SHA.fullmatch(revision) for revision in external_revisions)

    hooks = [hook for repository in repositories for hook in repository["hooks"]]
    hook_ids = {hook["id"] for hook in hooks}
    assert hook_ids >= {
        "gitleaks",
        "ruff-check",
        "ruff-format",
        "mypy",
        "app-lint",
        "app-typecheck",
        "repository-hygiene",
    }
    assert all("verify_public_release" not in hook.get("entry", "") for hook in hooks)


def test_worker_hooks_are_python_312_checks_and_never_request_mutation() -> None:
    repositories = _pre_commit_config()["repos"]
    assert isinstance(repositories, list)
    hooks = [hook for repository in repositories for hook in repository["hooks"]]
    hook_commands = {
        hook["id"]: [*shlex.split(hook.get("entry", "")), *hook.get("args", [])] for hook in hooks
    }

    forbidden_mutations = {"--fix", "--fix-only", "--unsafe-fixes"}
    assert all(forbidden_mutations.isdisjoint(command) for command in hook_commands.values())
    assert "--check" in hook_commands["ruff-format"]
    for hook_id in ("ruff-check", "ruff-format", "mypy", "pytest", "repository-hygiene"):
        command = hook_commands[hook_id]
        python_index = command.index("--python")
        assert command[python_index + 1] == "3.12"


def test_pre_commit_fails_without_changing_an_invalid_worker_file() -> None:
    original = "import sys\nimport os\n\ndef value( ):\n return 1\n"
    probe = REPOSITORY_ROOT / "worker" / ".release-gate-ruff-probe.py"
    assert not probe.exists()
    try:
        probe.write_text(original)
        result = run(
            ["pre-commit", "run", "--files", str(probe.relative_to(REPOSITORY_ROOT))],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        observed = probe.read_text()
    finally:
        probe.unlink(missing_ok=True)

    assert result.returncode != 0
    assert observed == original


def test_worker_image_uses_verified_python_and_uv_artifacts() -> None:
    dockerfile = (REPOSITORY_ROOT / "worker" / "Dockerfile").read_text()
    from_instructions = [
        line.split()[1] for line in dockerfile.splitlines() if line.startswith("FROM ")
    ]

    assert from_instructions == [
        "ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1",
        "python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a",
    ]
    assert "pip install" not in dockerfile
