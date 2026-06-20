"""Find related files within a PR's own changeset to give Claude cross-file context.

Only ever matches against `other_filenames` — the PR's own changed-file list from GitHub's API —
never against an arbitrary repo-wide file index. That keeps the attack surface bounded to files
the PR author already controls and can already see, with no path-traversal/arbitrary-file-read
risk from the import names extracted out of attacker-controlled diff text. Symlinked entries are
skipped outright: a symlinked "changed file" can resolve to a location that is technically inside
the workspace (e.g. `.git/config`) without being a file the PR actually changed, which the
resolve()+relative_to() containment check alone wouldn't catch.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MAX_RELATED_FILES = 3
MAX_RELATED_FILE_CHARS = 2000


def _basename_stem(path: str) -> str:
    return Path(path.replace("\\", "/")).stem


def _python_module_to_basename(module: str) -> str:
    return module.rsplit(".", 1)[-1]


_IMPORT_RULES: list[tuple[re.Pattern[str], Callable[[str], str]]] = [
    (re.compile(r"\bfrom\s+([\w.]+)\s+import\b"), _python_module_to_basename),
    (re.compile(r"\bimport\s+([\w.]+)(?!\s*;)"), _python_module_to_basename),
    (
        re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]|\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        _basename_stem,
    ),
    (re.compile(r"\bimport\s+(?:static\s+)?([\w.]+)\s*;"), _python_module_to_basename),
    (re.compile(r'#include\s*[<"]([^">]+)[">]'), _basename_stem),
]


@dataclass(frozen=True)
class RelatedFile:
    filename: str
    excerpt: str


def _exclude_removed_lines(diff_text: str) -> str:
    """Drop diff lines that were deleted (`-` prefix) so stale imports aren't matched."""
    return "\n".join(line for line in diff_text.splitlines() if not line.startswith("-"))


def _extract_referenced_basenames(diff_text: str) -> set[str]:
    text = _exclude_removed_lines(diff_text)
    basenames: set[str] = set()
    for pattern, extractor in _IMPORT_RULES:
        for match in pattern.finditer(text):
            for group in match.groups():
                if group:
                    basenames.add(extractor(group))
    return basenames


def _read_within_workspace(workspace_root: Path, candidate: str) -> str | None:
    candidate_path = workspace_root / candidate
    if candidate_path.is_symlink():
        return None

    resolved_root = workspace_root.resolve()
    resolved_candidate = candidate_path.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        return None

    try:
        return resolved_candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def find_related_files(
    target_filename: str,
    target_diff_text: str,
    other_filenames: list[str],
    workspace_root: Path,
) -> list[RelatedFile]:
    referenced_basenames = _extract_referenced_basenames(target_diff_text)
    if not referenced_basenames:
        return []

    related: list[RelatedFile] = []
    for candidate in other_filenames:
        if candidate == target_filename:
            continue
        if _basename_stem(candidate) not in referenced_basenames:
            continue

        content = _read_within_workspace(workspace_root, candidate)
        if content is None:
            continue

        related.append(RelatedFile(filename=candidate, excerpt=content[:MAX_RELATED_FILE_CHARS]))
        if len(related) >= MAX_RELATED_FILES:
            break

    return related
