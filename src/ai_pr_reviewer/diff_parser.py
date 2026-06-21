"""Parse unified-diff patch strings from the GitHub PR files API into line-numbered diffs."""

import re
from dataclasses import dataclass, field
from enum import StrEnum

_HUNK_HEADER_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,\d+)? \+(?P<new_start>\d+)(?:,\d+)? @@")
_DIFF_GIT_HEADER_RE = re.compile(r"^diff --git ")
_OLD_FILE_HEADER_RE = re.compile(r"^--- (?:a/(?P<old_path>.*)|/dev/null)$")
_NEW_FILE_HEADER_RE = re.compile(r"^\+\+\+ (?:b/(?P<new_path>.*)|/dev/null)$")


class LineType(StrEnum):
    CONTEXT = "context"
    ADDED = "added"
    REMOVED = "removed"


@dataclass(frozen=True)
class DiffLine:
    content: str
    line_type: LineType
    old_lineno: int | None
    new_lineno: int | None


@dataclass(frozen=True)
class FileDiff:
    filename: str
    lines: list[DiffLine] = field(default_factory=list)

    def commentable_lines(self) -> set[int]:
        """New-file line numbers that GitHub will accept for a RIGHT-side inline comment."""
        return {
            line.new_lineno
            for line in self.lines
            if line.line_type in (LineType.ADDED, LineType.CONTEXT) and line.new_lineno is not None
        }

    def old_lineno_for(self, new_lineno: int) -> int | None:
        """The corresponding old-file line number for a commentable line, or None if added.

        Needed by providers (GitLab) whose comment-positioning contract requires both the old
        and new line number for unchanged context lines, since the line exists on both sides.
        """
        for line in self.lines:
            if line.new_lineno == new_lineno and line.line_type == LineType.CONTEXT:
                return line.old_lineno
        return None


def parse_patch(filename: str, patch: str | None) -> FileDiff:
    if not patch:
        return FileDiff(filename=filename, lines=[])

    lines: list[DiffLine] = []
    old_lineno = new_lineno = 0

    for raw_line in patch.splitlines():
        header_match = _HUNK_HEADER_RE.match(raw_line)
        if header_match:
            old_lineno = int(header_match.group("old_start"))
            new_lineno = int(header_match.group("new_start"))
            continue

        if not raw_line or raw_line.startswith("\\"):
            continue

        marker, content = raw_line[0], raw_line[1:]
        if marker == "+":
            lines.append(DiffLine(content, LineType.ADDED, None, new_lineno))
            new_lineno += 1
        elif marker == "-":
            lines.append(DiffLine(content, LineType.REMOVED, old_lineno, None))
            old_lineno += 1
        elif marker == " ":
            lines.append(DiffLine(content, LineType.CONTEXT, old_lineno, new_lineno))
            old_lineno += 1
            new_lineno += 1

    return FileDiff(filename=filename, lines=lines)


def split_unified_diff_by_file(combined_diff: str) -> dict[str, str]:
    """Split a multi-file unified diff (as returned by Bitbucket's PR /diff endpoint) by file.

    Returns each file's hunk-only text (starting from the first `@@` line), in the same shape
    `parse_patch()` already expects — the `diff --git`/`index`/`---`/`+++` header lines are
    dropped since they carry no line-numbering information.

    Filenames are derived from the `---`/`+++` lines, not the `diff --git a/X b/Y` header: the
    header is ambiguous for any path containing the literal substring " b/" (greedy matching
    can't tell where "a/X" ends and "b/Y" begins), while `+++ b/<path>` has nothing after the
    path on that line, so there's no ambiguity to resolve.
    """
    files: dict[str, list[str]] = {}
    current_filename: str | None = None
    pending_old_path: str | None = None
    in_hunk = False

    for raw_line in combined_diff.splitlines():
        if _DIFF_GIT_HEADER_RE.match(raw_line):
            current_filename = None
            pending_old_path = None
            in_hunk = False
            continue

        old_match = _OLD_FILE_HEADER_RE.match(raw_line)
        if old_match:
            pending_old_path = old_match.group("old_path")
            continue

        new_match = _NEW_FILE_HEADER_RE.match(raw_line)
        if new_match:
            current_filename = new_match.group("new_path") or pending_old_path
            if current_filename is not None:
                files[current_filename] = []
            continue

        if current_filename is None:
            continue

        if raw_line.startswith("@@"):
            in_hunk = True

        if in_hunk:
            files[current_filename].append(raw_line)

    return {filename: "\n".join(file_lines) for filename, file_lines in files.items()}
