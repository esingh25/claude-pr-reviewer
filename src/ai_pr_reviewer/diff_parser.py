"""Parse unified-diff patch strings from the GitHub PR files API into line-numbered diffs."""

import re
from dataclasses import dataclass, field
from enum import StrEnum

_HUNK_HEADER_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,\d+)? \+(?P<new_start>\d+)(?:,\d+)? @@")


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
