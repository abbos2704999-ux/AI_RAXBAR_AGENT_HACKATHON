"""Repository safety scan.

Fails if any git-tracked file in the repo matches an obvious
credential/secret pattern or a known-sensitive filename. This is a simple,
deliberately non-exhaustive net -- not a full secret scanner -- meant to
catch obvious accidents (a committed private key, a .clasp.json, a
service-account JSON, a hardcoded token/password assignment).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# This scanner's own file is excluded from content scanning: it necessarily
# contains the pattern strings/names below as literals, which would
# otherwise self-match.
_SELF = Path(__file__).resolve()

_FORBIDDEN_FILENAMES = {".clasp.json", ".clasprc.json"}

_FORBIDDEN_FILENAME_MARKERS = ("service-account", "service_account")

_CONTENT_PATTERNS = [
    re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
    re.compile(r'"type"\s*:\s*"service_account"'),
    re.compile(
        r"""(?ix)
        \b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password)
        \s*[:=]\s*
        ['"][A-Za-z0-9/_\-.]{8,}['"]
        """
    ),
]

_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".woff", ".woff2",
}


def _tracked_files() -> list[Path]:
    # Tracked files plus untracked-but-not-gitignored files: this is the set
    # of files that *could* end up committed, which is what a pre-commit
    # safety scan actually needs to cover.
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [_REPO_ROOT / line for line in result.stdout.splitlines() if line]


def test_no_forbidden_filenames_tracked():
    for path in _tracked_files():
        assert path.name not in _FORBIDDEN_FILENAMES, f"forbidden filename tracked: {path}"
        lower = path.name.lower()
        if lower.endswith(".json"):
            for marker in _FORBIDDEN_FILENAME_MARKERS:
                assert marker not in lower, f"forbidden filename pattern tracked: {path}"


def test_no_obvious_credential_patterns_in_tracked_files():
    offenders: list[str] = []
    for path in _tracked_files():
        if path.resolve() == _SELF:
            continue
        if path.suffix.lower() in _BINARY_SUFFIXES:
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in _CONTENT_PATTERNS:
            if pattern.search(content):
                offenders.append(f"{path.relative_to(_REPO_ROOT)} :: {pattern.pattern[:40]}")

    assert not offenders, "possible secret pattern(s) found: " + "; ".join(offenders)
