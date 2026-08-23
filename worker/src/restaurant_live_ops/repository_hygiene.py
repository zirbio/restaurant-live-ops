"""Gate de neutralidad para preparar un árbol publicable."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from subprocess import run
from tarfile import open as open_tarfile
from urllib.parse import SplitResult, urlsplit

DEFAULT_FORBIDDEN_HASHES = frozenset(
    {
        "c1f5def06c9c8066f2388eb67559d9ccb16892f0e243d69120802df77e455772",
        "54fa0ac6fb7ba4b0ec2dc9fc8f7d5c553c5c3be6f964e3f6dd49795adda51010",
        "d944bfb18e1258bfa8deb6009a3067b89caad6ad97c83e0f3459b1481f686d1b",
        "c5099a6000c2be06c62bd9ca2dd25526efb177e0d7193746a2a163f7f4f48947",
        "3523c8b932f8be0457a4fc784c9cba44cefb2ee1025fab067aa87346d9975c12",
        "58597e75c94391867058c789444da3a986953bcc54170f6b48ddef51e507e0c4",
        "08d27e8c9a41aa68702df93c7a0a7ea7ba0e22c16d14f9ec2c492c81671fc4a4",
        "375eca5944bc3c25474069b7d151fd48788a4d63f1298f1dc49dd79bc6d4dd72",
        "be46052367982fe3ab599150ca8995030fb41ea8a0a0dc17bcfaef59c4a2ed6b",
    }
)
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
    }
)
CONSTRUCTION_ONLY_PATH_PREFIXES = (
    (".superpowers",),
    ("docs", "superpowers"),
)
CONSTRUCTION_EXPORT_IGNORE_RULES = frozenset(
    {
        "/.superpowers export-ignore",
        "/docs/superpowers export-ignore",
    }
)
PUBLIC_DEPENDENCY_URLS = frozenset(
    {
        "https://github.com/gitleaks/gitleaks",
        "https://github.com/astral-sh/ruff-pre-commit",
    }
)
PUBLIC_PACKAGE_METADATA_URLS = frozenset(
    {
        "https://github.com/bgub/eta",
        "https://github.com/fb55/entities",
        "https://github.com/sponsors/Boshen",
        "https://github.com/sponsors/Brooooooklyn",
        "https://github.com/sponsors/SuperchupuDev",
        "https://github.com/sponsors/ai",
        "https://github.com/sponsors/antfu",
        "https://github.com/sponsors/epoberezkin",
        "https://github.com/sponsors/fastify",
        "https://github.com/sponsors/inspect-js",
        "https://github.com/sponsors/isaacs",
        "https://github.com/sponsors/jonschlinkert",
        "https://github.com/sponsors/ljharb",
        "https://github.com/sponsors/sindresorhus",
        "https://github.com/sponsors/sxzz",
        "https://github.com/vitejs/vite",
        "https://opencollective.com/babel",
        "https://opencollective.com/browserslist",
        "https://opencollective.com/core-js",
        "https://opencollective.com/debug",
        "https://opencollective.com/fastify",
        "https://opencollective.com/parcel",
        "https://opencollective.com/postcss/",
        "https://opencollective.com/vitest",
        "https://tidelift.com/funding/github/npm/browserslist",
        "https://tidelift.com/funding/github/npm/caniuse-lite",
        "https://tidelift.com/funding/github/npm/postcss",
    }
)
SAFE_URL_HOSTS = frozenset(
    {
        "example.com",
        "localhost",
        "your-project.supabase.co",
    }
)
DOCUMENTATION_PATH_PREFIXES = frozenset(
    {
        ("docs.github.com", "/"),
        ("docs.netlify.com", "/"),
        ("docs.python.org", "/"),
        ("docs.railway.com", "/"),
        ("playwright.dev", "/python/"),
        ("react.dev", "/learn/"),
        ("supabase.com", "/docs/"),
        ("vercel.com", "/docs/"),
        ("vite.dev", "/guide/"),
        ("www.typescriptlang.org", "/docs/"),
    }
)
ABSOLUTE_USER_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:/(?:users|home)(?=$|[\\/])|[A-Za-z]:\\users(?=$|[\\/]))",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")
IDENTIFIER_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]+")
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
LOCALIZED_OPERATIONAL_NARRATIVE_PATTERNS = (
    re.compile(r"\bverificad[oa]s?\s+en\s+(?:los\s+)?\d+\s+(?:local(?:es)?|restaurantes?)\b", re.I),
    re.compile(r"\b(?:fichaje|turno|muestra|incidente|dato|fuente)\s+real\b", re.I),
    re.compile(r"\b(?:este|ese|aquel)\s+mismo\s+d[ií]a\b", re.I),
    re.compile(
        r"\b(?:sobre|entre|de\s+los)\s+\d[\d.,]*\s+(?:fichajes|personas|visitas|muestras)\b",
        re.I,
    ),
)
CREDENTIAL_PATTERN = re.compile(
    r"(?ix)\b(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|pwd|secret|token)\b\s*(?:=(?!=)\s*|:\s*)(?P<value>\"[^\"]*\"|'[^']*'|[^,;#\s]+(?:\s+[^,;#\s]+)*)"
)
TRIPLE_QUOTED_CREDENTIAL_PATTERN = re.compile(
    r"(?ix)\b(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|pwd|secret|token)\b\s*(?:=(?!=)\s*|:\s*)(?:\"\"\"|''')"
)
ENVIRONMENT_NAME = r"[A-Z][A-Z0-9_]*"
EXACT_ENVIRONMENT_REFERENCE_PATTERN = re.compile(
    rf"^(?:os\.getenv\(\"{ENVIRONMENT_NAME}\"\)|_required\(\"{ENVIRONMENT_NAME}\"\)|process\.env\.{ENVIRONMENT_NAME}|import\.meta\.env\.{ENVIRONMENT_NAME})$"
)
ENVIRONMENT_PLACEHOLDER_PATTERN = re.compile(rf"^\$\{{{ENVIRONMENT_NAME}\}}$")
ANGLE_PLACEHOLDER_PATTERN = re.compile(r"^<[^<>\s]+>$")
TYPE_ANNOTATION_VALUES = frozenset(
    {"Any", "None", "NoneType", "bool", "bytes", "float", "int", "object", "str", "unknown"}
)
TYPE_ANNOTATION_PATTERN = re.compile(
    rf"^(?:{'|'.join(TYPE_ANNOTATION_VALUES)})(?:\s*\|\s*(?:{'|'.join(TYPE_ANNOTATION_VALUES)}))*$"
)
NON_LITERAL_CODE_VALUE_PATTERN = re.compile(
    r"^(?:[a-z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*|[a-z][a-z0-9]*_[a-z0-9_]*|[a-z][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\(\))$"
)
KNOWN_PUBLIC_URL_HOSTS = frozenset(
    {
        "example.com",
        "files.pythonhosted.org",
        "github.com",
        "opencollective.com",
        "pypi.org",
        "registry.npmjs.org",
        "tidelift.com",
        "www.w3.org",
        "your-project.supabase.co",
    }
    | {hostname for hostname, _ in DOCUMENTATION_PATH_PREFIXES}
)
NON_NETWORK_IDENTIFIER_URLS = frozenset({"http://www.w3.org/2000/svg"})


@dataclass(frozen=True, order=True)
class Violation:
    rule: str
    path: str
    line: int


def scan_tree(
    root: Path,
    *,
    forbidden_hashes: frozenset[str] = DEFAULT_FORBIDDEN_HASHES,
) -> list[Violation]:
    """Escanea texto versionable y devuelve infracciones sin imprimir contenido."""
    if not root.exists() or not root.is_dir():
        raise ValueError("scan root must be an existing directory")

    violations: list[Violation] = []
    for path in _iter_scannable_files(root):
        relative_path = path.relative_to(root).as_posix()
        try:
            text = _read_text(path)
        except UnicodeDecodeError:
            violations.append(Violation("undecodable-text", relative_path, 0))
            continue
        if text is None:
            continue
        violations.extend(
            _scan_text(
                text,
                relative_path=relative_path,
                forbidden_hashes=forbidden_hashes,
            )
        )
    return sorted(
        violations,
        key=lambda violation: (violation.path, violation.line, violation.rule),
    )


def scan_git_archive(
    root: Path,
    *,
    forbidden_hashes: frozenset[str] = DEFAULT_FORBIDDEN_HASHES,
) -> list[Violation]:
    """Escanea exactamente el archivo exportable de HEAD sin extraerlo."""
    if not root.exists() or not root.is_dir():
        raise ValueError("scan root must be an existing directory")
    result = run(
        ["git", "archive", "--worktree-attributes", "--format=tar", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("scan root must be a git repository with HEAD")

    violations: list[Violation] = []
    with open_tarfile(fileobj=BytesIO(result.stdout)) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            content = extracted.read()
            try:
                text = _decode_text(content)
            except UnicodeDecodeError:
                violations.append(Violation("undecodable-text", member.name, 0))
                continue
            if text is None:
                continue
            violations.extend(
                _scan_text(
                    text,
                    relative_path=member.name,
                    forbidden_hashes=forbidden_hashes,
                )
            )
    return sorted(
        violations, key=lambda violation: (violation.path, violation.line, violation.rule)
    )


def _iter_scannable_files(root: Path) -> list[Path]:
    construction_paths_are_export_ignored = _construction_paths_are_export_ignored(root)
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_DIRECTORY_NAMES for part in path.relative_to(root).parts)
        and not (
            construction_paths_are_export_ignored
            and any(
                path.relative_to(root).parts[: len(prefix)] == prefix
                for prefix in CONSTRUCTION_ONLY_PATH_PREFIXES
            )
        )
    ]


def _read_text(path: Path) -> str | None:
    return _decode_text(path.read_bytes())


def _decode_text(content: bytes) -> str | None:
    if content.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return content.decode("utf-32")
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16")
    if b"\x00" in content:
        return None
    return content.decode("utf-8")


def _scan_text(
    text: str,
    *,
    relative_path: str,
    forbidden_hashes: frozenset[str],
) -> list[Violation]:
    violations: list[Violation] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _contains_forbidden_identifier(line, forbidden_hashes):
            violations.append(Violation("forbidden-token", relative_path, line_number))
        if any(not _is_synthetic_email(email) for email in EMAIL_PATTERN.findall(line)):
            violations.append(Violation("email", relative_path, line_number))
        if ABSOLUTE_USER_PATH_PATTERN.search(line):
            violations.append(Violation("absolute-user-path", relative_path, line_number))
        if TRIPLE_QUOTED_CREDENTIAL_PATTERN.search(line) or any(
            _is_credential(value) for value in _credential_values(line)
        ):
            violations.append(Violation("credential", relative_path, line_number))
        if any(not _is_documentation_url(match.group()) for match in URL_PATTERN.finditer(line)):
            violations.append(Violation("deployment-identifier", relative_path, line_number))
        if any(pattern.search(line) for pattern in LOCALIZED_OPERATIONAL_NARRATIVE_PATTERNS):
            violations.append(Violation("operational-narrative", relative_path, line_number))
    return violations


def _contains_forbidden_identifier(line: str, forbidden_hashes: frozenset[str]) -> bool:
    if any(_digest(token) in forbidden_hashes for token in TOKEN_PATTERN.findall(line)):
        return True
    words = IDENTIFIER_WORD_PATTERN.findall(line)
    return any(
        _digest(" ".join(words[index : index + width])) in forbidden_hashes
        for width in range(2, min(4, len(words)) + 1)
        for index in range(0, len(words) - width + 1)
    )


def _digest(value: str) -> str:
    return sha256(value.casefold().encode()).hexdigest()


def _is_synthetic_email(email: str) -> bool:
    normalized_email = email.casefold()
    return normalized_email.endswith("@example.com") or normalized_email.rsplit("@", 1)[1].endswith(
        ".test"
    )


def _credential_values(line: str) -> list[str]:
    return [
        match.group("value").strip().strip("'\"") for match in CREDENTIAL_PATTERN.finditer(line)
    ]


def _is_credential(value: str) -> bool:
    return not (
        not value
        or TYPE_ANNOTATION_PATTERN.fullmatch(value) is not None
        or value.casefold() in {"none", "null", "undefined"}
        or ANGLE_PLACEHOLDER_PATTERN.fullmatch(value) is not None
        or ENVIRONMENT_PLACEHOLDER_PATTERN.fullmatch(value) is not None
        or EXACT_ENVIRONMENT_REFERENCE_PATTERN.fullmatch(value) is not None
        # Data-flow simple sin literales no almacena una credencial en el repositorio.
        or NON_LITERAL_CODE_VALUE_PATTERN.fullmatch(value) is not None
    )


def _is_documentation_url(url: str) -> bool:
    if url in NON_NETWORK_IDENTIFIER_URLS:
        return True
    if "?" in url or "#" in url:
        return False
    normalized_url = url.rstrip(".,;:!?)]}")
    parsed_url = urlsplit(normalized_url)
    hostname = parsed_url.hostname
    if hostname is None:
        return False
    if (
        parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        return False
    normalized_host = hostname.casefold().rstrip(".")
    if parsed_url.scheme == "http":
        return normalized_host in {"127.0.0.1", "localhost"}
    if parsed_url.scheme != "https":
        return False
    if any(normalized_host.startswith(f"{public_host}.") for public_host in KNOWN_PUBLIC_URL_HOSTS):
        return False
    canonical_url = f"{parsed_url.scheme}://{normalized_host}{parsed_url.path}"
    if canonical_url in PUBLIC_DEPENDENCY_URLS | PUBLIC_PACKAGE_METADATA_URLS:
        return True
    if _is_public_package_url(parsed_url):
        return True
    if normalized_host in {"127.0.0.1", "localhost", "www.w3.org"}:
        return True
    if normalized_host.endswith((".test", ".invalid")):
        return True
    if normalized_host in SAFE_URL_HOSTS:
        return True
    return any(
        normalized_host == documentation_host and parsed_url.path.startswith(path_prefix)
        for documentation_host, path_prefix in DOCUMENTATION_PATH_PREFIXES
    )


def _construction_paths_are_export_ignored(root: Path) -> bool:
    attributes = root / ".gitattributes"
    if not attributes.is_file():
        return False
    return CONSTRUCTION_EXPORT_IGNORE_RULES <= {
        line.strip() for line in attributes.read_text().splitlines() if line.strip()
    }


def _is_public_package_url(parsed_url: SplitResult) -> bool:
    if (
        parsed_url.scheme != "https"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.port is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        return False
    hostname = parsed_url.hostname.casefold() if parsed_url.hostname else ""
    if hostname == "registry.npmjs.org":
        return parsed_url.path.startswith("/") and parsed_url.path != "/"
    if hostname == "pypi.org":
        return parsed_url.path in {"/simple", "/simple/"}
    return hostname == "files.pythonhosted.org" and parsed_url.path.startswith("/packages/")


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comprueba que un árbol no expone datos privados.")
    parser.add_argument("--git-archive", action="store_true")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parsed_arguments = parser.parse_args(arguments)
    try:
        violations = (
            scan_git_archive(parsed_arguments.root)
            if parsed_arguments.git_archive
            else scan_tree(parsed_arguments.root)
        )
    except ValueError:
        sys.stderr.write("error: scan root must be an existing directory\n")
        return 2
    for violation in violations:
        sys.stdout.write(f"{violation.rule}: {violation.path}:{violation.line}\n")
    return 1 if violations else 0
