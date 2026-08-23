import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from subprocess import run
from tarfile import open as open_tarfile

from pytest import raises

from restaurant_live_ops.repository_hygiene import scan_tree

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def digest(value: str) -> str:
    return sha256(value.casefold().encode()).hexdigest()


def unsafe_text(*parts: str) -> str:
    return "".join(parts)


def test_rejects_forbidden_token_by_digest(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("PRIVATE_TOKEN = 'legacy-brand'\n")

    violations = scan_tree(tmp_path, forbidden_hashes=frozenset({digest("legacy-brand")}))

    assert [(v.rule, v.path, v.line) for v in violations] == [("forbidden-token", "module.py", 1)]


def test_rejects_known_private_identifier_without_echoing_it(tmp_path: Path) -> None:
    private_identifier = "".join(chr(value) for value in (86, 65, 45, 76, 105, 118, 101))
    (tmp_path / "module.py").write_text(f'LABEL = "{private_identifier}"\n')

    violations = scan_tree(tmp_path)

    assert [(v.rule, v.path, v.line) for v in violations] == [("forbidden-token", "module.py", 1)]
    assert private_identifier not in str(violations)


def test_rejects_localized_operational_narrative_without_echoing_it(tmp_path: Path) -> None:
    narratives = [
        unsafe_text("caso verifi", "cado en ", "3", " locales"),
        unsafe_text("el fichaje ", "real más largo quedó registrado"),
        unsafe_text("comparado en ", "este mismo ", "día"),
        unsafe_text("sobre ", "3874", " fichajes observados"),
    ]
    (tmp_path / "notes.py").write_text("\n".join(narratives))

    violations = scan_tree(tmp_path, forbidden_hashes=frozenset())

    assert [(v.rule, v.path, v.line) for v in violations] == [
        ("operational-narrative", "notes.py", line) for line in range(1, 5)
    ]
    assert all(narrative not in str(violations) for narrative in narratives)


def test_cli_scans_the_committed_git_archive_not_only_the_worktree(tmp_path: Path) -> None:
    private_identifier = "".join(chr(value) for value in (86, 65, 32, 76, 105, 118, 101))
    (tmp_path / "private.txt").write_text(private_identifier)
    run(["git", "init", "-q"], cwd=tmp_path, check=True)
    run(["git", "add", "private.txt"], cwd=tmp_path, check=True)
    run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "test fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "private.txt").write_text("neutral\n")

    result = run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "check_repository_hygiene.py"),
            "--git-archive",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    expected_rule = unsafe_text("forbidden-", "to", "ken")
    assert result.stdout == f"{expected_rule}: private.txt:1\n"
    assert private_identifier not in result.stdout + result.stderr


def test_rejects_email_path_and_live_identifier(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "owner",
            "@company.org\n",
            "/Users",
            "/owner/private\n",
            "https:/",
            "/abcdefghijklmnopqrst.supabase.co\n",
        )
    )

    rules = {violation.rule for violation in scan_tree(tmp_path, forbidden_hashes=frozenset())}

    assert rules == {"email", "absolute-user-path", "deployment-identifier"}


def test_rejects_non_documentary_deployment_url(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text("https:/", "/worker-production.up.railway.app\n")
    )

    violations = scan_tree(tmp_path, forbidden_hashes=frozenset())

    assert [(violation.rule, violation.path, violation.line) for violation in violations] == [
        ("deployment-identifier", "settings.txt", 1)
    ]


def test_rejects_project_urls_under_documentation_hosts(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        "https://"
        "app.netlify.com/sites/private-id\n"
        "https://"
        "railway.com/project/private-id\n"
        "https://"
        "github.com/org/private-repo\n"
    )

    violations = scan_tree(tmp_path, forbidden_hashes=frozenset())

    assert [(violation.rule, violation.path, violation.line) for violation in violations] == [
        ("deployment-identifier", "settings.txt", 1),
        ("deployment-identifier", "settings.txt", 2),
        ("deployment-identifier", "settings.txt", 3),
    ]


def test_allows_documented_placeholders(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        unsafe_text(
            "VITE_SUPABASE_URL=https:/",
            "/your-project.supabase.co\nCONTACT=security@example.com\n",
        )
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_allows_public_dependency_registry(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text(
        '"resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz"\n'
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_ignores_cache_directories_and_binary_files(tmp_path: Path) -> None:
    cache_file = tmp_path / ".venv" / "settings.txt"
    cache_file.parent.mkdir()
    cache_file.write_text("owner@company.test\n")
    (tmp_path / "image.bin").write_bytes(b"\x00owner@company.test")

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_ignores_construction_artifacts(tmp_path: Path) -> None:
    (tmp_path / ".gitattributes").write_text(
        "/.superpowers export-ignore\n/docs/superpowers export-ignore\n"
    )
    construction_report = tmp_path / ".superpowers" / "plan.md"
    construction_report.parent.mkdir()
    construction_report.write_text(unsafe_text("owner", "@company.org\n"))
    archived_document = tmp_path / "docs" / "superpowers" / "history.md"
    archived_document.parent.mkdir(parents=True)
    archived_document.write_text(unsafe_text("/Users", "/owner/private\n"))

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_public_archive_excludes_construction_artifacts() -> None:
    result = run(
        ["git", "archive", "--worktree-attributes", "--format=tar", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    with open_tarfile(fileobj=BytesIO(result.stdout)) as archive:
        names = archive.getnames()

    assert not any(name == ".superpowers" or name.startswith(".superpowers/") for name in names)
    assert not any(
        name == "docs/superpowers" or name.startswith("docs/superpowers/") for name in names
    )


def test_allows_reserved_synthetic_domains(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "owner@company.test\nhttps:/",
            "/sales.example.test\nhttps:/",
            "/test.supabase.invalid\n",
        )
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_scans_archive_documents(tmp_path: Path) -> None:
    archived_document = tmp_path / "docs" / "mapa-de-datos.md"
    archived_document.parent.mkdir()
    archived_document.write_text("owner" + "@company.org\n")

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("email", "docs/mapa-de-datos.md", 1)]


def test_scans_tests_and_lockfiles_for_private_values(tmp_path: Path) -> None:
    fixture = tmp_path / "worker" / "tests" / "fixture.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("operator" + "@private.example\n")
    (tmp_path / "package-lock.json").write_text(
        '"resolved": "https:/' + '/private.example/package.tgz"\n'
    )
    (tmp_path / "uv.lock").write_text("api_" + "to" + 'ken = "private-token-123"\n')

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [
        ("deployment-identifier", "package-lock.json", 1),
        ("credential", "uv.lock", 1),
        ("email", "worker/tests/fixture.py", 1),
    ]


def test_rejects_quoted_and_unquoted_common_credential_variants(tmp_path: Path) -> None:
    fixture = tmp_path / "worker" / "tests" / "fixture.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        unsafe_text(
            "auth",
            "To",
            'ken = "non-placeholder"\n',
            "api",
            "Key=unquoted-value\n",
            "client",
            "_secret = 'another-value'\n",
            "pass",
            "wd = plain-value\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [
        ("credential", "worker/tests/fixture.py", 1),
        ("credential", "worker/tests/fixture.py", 2),
        ("credential", "worker/tests/fixture.py", 3),
        ("credential", "worker/tests/fixture.py", 4),
    ]


def test_rejects_credential_keys_with_separator_and_casing_variants(tmp_path: Path) -> None:
    fixture = tmp_path / "worker" / "tests" / "fixture.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        unsafe_text(
            "api",
            'Key = "literal-one"\n',
            "api",
            "_key: literal-two\n",
            "api",
            "-key=literal-three\n",
            "access",
            "To",
            'ken: "literal-four"\n',
            "auth",
            "-to",
            "ken = literal-five\n",
            "client",
            "_sec",
            "ret: literal-six\n",
            "pass",
            'word = "literal-seven"\n',
            "pass",
            "wd: literal-eight\n",
            "pw",
            "d = literal-nine\n",
            "sec",
            "ret: literal-ten\n",
            "to",
            'ken = "literal-eleven"\n',
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("credential", "worker/tests/fixture.py", line) for line in range(1, 12)]


def test_allows_exact_environment_references_and_absent_credential_values(tmp_path: Path) -> None:
    fixture = tmp_path / "settings.env"
    fixture.write_text(
        unsafe_text(
            "pass",
            'word=os.getenv("UPPERCASE_ENV_NAME")\n',
            "pass",
            'word=_required("UPPERCASE_ENV_NAME")\n',
            "pass",
            "word=process.env.UPPERCASE_ENV_NAME\n",
            "pass",
            "word=import.meta.env.UPPERCASE_ENV_NAME\n",
            "pass",
            "word=<PASSWORD>\n",
            "pass",
            "word=${UPPERCASE_ENV_NAME}\n",
            "pass",
            "word=\n",
            "pass",
            "word=null\n",
            "pass",
            "word=None\n",
        )
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_rejects_nonexact_environment_indirection(tmp_path: Path) -> None:
    fixture = tmp_path / "settings.env"
    fixture.write_text(
        unsafe_text(
            "pass",
            'word=os.getenv("lowercase_env")\n',
            "pass",
            'word=_required("UPPERCASE_ENV_NAME", "fallback")\n',
            "pass",
            "word=process.env.UPPERCASE_ENV_NAME || fallback\n",
            "pass",
            "word=${lowercase_env}\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("credential", "settings.env", line) for line in range(1, 5)]


def test_allows_non_literal_runtime_credential_expressions(tmp_path: Path) -> None:
    fixture = tmp_path / "settings.py"
    fixture.write_text(
        unsafe_text(
            "pass",
            "word=generatedCredential\n",
            "to",
            "ken=codigo.trim()\n",
            "sec",
            "ret=generated_credential\n",
            "api",
            "Key=obj.method()\n",
        )
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_rejects_non_literal_expressions_that_embed_literals(tmp_path: Path) -> None:
    fixture = tmp_path / "settings.py"
    fixture.write_text(
        unsafe_text(
            "pass",
            'word=obj.method("literal")\n',
            "to",
            'ken=generatedCredential || "fallback"\n',
            "sec",
            'ret=generated_credential + "literal"\n',
            "api",
            'Key=make_value("literal")\n',
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("credential", "settings.py", line) for line in range(1, 5)]


def test_rejects_triple_quoted_sensitive_assignments_on_their_first_line(tmp_path: Path) -> None:
    fixture = tmp_path / "settings.py"
    fixture.write_text(
        unsafe_text(
            "pass",
            'word="""same-line"""\n',
            "pass",
            'word="""\n',
            "pass",
            "word='''same-line'''\n",
            "pass",
            "word='''\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("credential", "settings.py", line) for line in range(1, 5)]


def test_rejects_backtick_quoted_sensitive_assignment(tmp_path: Path) -> None:
    fixture = tmp_path / "settings.py"
    fixture.write_text(unsafe_text("pass", "word=`literal`\n"))

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("credential", "settings.py", 1)]


def test_rejects_dependency_resolver_url_with_query_token(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text(
        unsafe_text(
            '"resolved": "https:/',
            "/registry.npmjs.org/example/-/example-1.0.0.tgz?to",
            'ken=non-placeholder"\n',
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("credential", "package-lock.json", 1), ("deployment-identifier", "package-lock.json", 1)]


def test_rejects_documentation_url_with_sensitive_query_key(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text("https:/", "/supabase.com/docs/guides?", "key=non-placeholder\n")
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("deployment-identifier", "settings.txt", 1)]


def test_rejects_documentation_urls_with_userinfo_query_or_fragment(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "https:/",
            "/user!@supabase.com/docs/guides\n",
            "https:/",
            "/supabase.com/docs/guides?source=public\n",
            "https:/",
            "/supabase.com/docs/guides#section\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("deployment-identifier", "settings.txt", line) for line in range(1, 4)]


def test_rejects_raw_markers_http_and_lookalikes_in_documentation_urls(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "https:/",
            "/supabase.com/docs?\n",
            "https:/",
            "/supabase.com/docs#\n",
            "http:/",
            "/supabase.com/docs\n",
            "https:/",
            "/user!@supabase.com/docs\n",
            "https:/",
            "/supabase.com.example.test/docs\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("deployment-identifier", "settings.txt", line) for line in range(1, 6)]


def test_allows_https_documentation_and_explicit_local_development_urls(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "https:/",
            "/SUPABASE.COM/docs/\n",
            "https:/",
            "/registry.npmjs.org/example/-/example-1.0.0.tgz\n",
            "http:/",
            "/localhost:3000\n",
            "http:/",
            "/127.0.0.1:3000\n",
        )
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_allows_exact_svg_namespace_identifier(tmp_path: Path) -> None:
    (tmp_path / "icon.svg").write_text(
        unsafe_text('<svg xmlns="http:/', '/www.w3.org/2000/svg"></svg>\n')
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_allows_exact_public_url_with_casefolded_hostname(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text("https:/", "/GITHUB.COM/gitleaks/gitleaks\n")
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_detects_case_insensitive_url_schemes_before_validating_them(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "HTTP:/",
            "/supabase.com/docs/\n",
            "HtTpS:/",
            "/SUPABASE.com/docs/\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("deployment-identifier", "settings.txt", 1)]


def test_allows_public_resolvers_inside_lockfiles(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text(
        '"resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz"\n'
    )
    (tmp_path / "uv.lock").write_text(
        'source = { registry = "https://pypi.org/simple" }\n'
        'wheel = { url = "https://files.pythonhosted.org/packages/example.whl" }\n'
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_allows_public_config_urls(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        "http://127.0.0.1:3000\nhttps://www.w3.org/2000/svg\nhttps://github.com/gitleaks/gitleaks\n"
    )

    assert scan_tree(tmp_path, forbidden_hashes=frozenset()) == []


def test_rejects_windows_user_path(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text("C:\\Users\\owner\\private\n")

    violations = scan_tree(tmp_path, forbidden_hashes=frozenset())

    assert [(violation.rule, violation.path, violation.line) for violation in violations] == [
        ("absolute-user-path", "settings.txt", 1)
    ]


def test_rejects_personal_paths_case_insensitively(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "/users",
            "/owner/private\n",
            "C:\\users",
            "\\owner\\private\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [
        ("absolute-user-path", "settings.txt", 1),
        ("absolute-user-path", "settings.txt", 2),
    ]


def test_rejects_personal_path_roots_and_descendants_without_matching_words(tmp_path: Path) -> None:
    (tmp_path / "settings.txt").write_text(
        unsafe_text(
            "/Us",
            "ers\n",
            "/us",
            "ers/owner\n",
            "/ho",
            "me\n",
            "C:\\Us",
            "ers\n",
            "C:\\us",
            "ers\\owner\n",
            "prefix/Users\n",
            "/Userspace\n",
            "C:\\Userspace\n",
        )
    )

    assert [
        (v.rule, v.path, v.line) for v in scan_tree(tmp_path, forbidden_hashes=frozenset())
    ] == [("absolute-user-path", "settings.txt", line) for line in range(1, 6)]


def test_rejects_non_binary_undecodable_text(tmp_path: Path) -> None:
    (tmp_path / "legacy.txt").write_bytes(b"\xffinvalid")

    violations = scan_tree(tmp_path, forbidden_hashes=frozenset())

    assert [(violation.rule, violation.path, violation.line) for violation in violations] == [
        ("undecodable-text", "legacy.txt", 0)
    ]


def test_scans_utf16_text(tmp_path: Path) -> None:
    (tmp_path / "legacy.txt").write_bytes(unsafe_text("owner", "@company.org\n").encode("utf-16"))

    violations = scan_tree(tmp_path, forbidden_hashes=frozenset())

    assert [(violation.rule, violation.path, violation.line) for violation in violations] == [
        ("email", "legacy.txt", 1)
    ]


def test_rejects_missing_or_file_scan_root(tmp_path: Path) -> None:
    file_root = tmp_path / "settings.txt"
    file_root.write_text("safe\n")

    with raises(ValueError, match="existing directory"):
        scan_tree(tmp_path / "missing")
    with raises(ValueError, match="existing directory"):
        scan_tree(file_root)


def test_cli_reports_location_without_sensitive_value(tmp_path: Path) -> None:
    secret_email = unsafe_text("owner", "@company.org")
    (tmp_path / "settings.txt").write_text(f"{secret_email}\n")

    result = run(
        [sys.executable, "scripts/check_repository_hygiene.py", str(tmp_path)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "email: settings.txt:1" in result.stdout
    assert secret_email not in result.stdout
    assert result.stderr == ""


def test_cli_rejects_invalid_root_without_printing_its_path(tmp_path: Path) -> None:
    invalid_root = tmp_path / "private-location"

    result = run(
        [sys.executable, "scripts/check_repository_hygiene.py", str(invalid_root)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "existing directory" in result.stderr
    assert str(invalid_root) not in result.stderr
