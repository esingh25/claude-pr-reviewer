"""Provider-agnostic types shared by every VCS backend (GitHub, GitLab, ...).

review_engine.py depends only on these, never on a specific provider's REST shapes, so adding a
new backend means writing an adapter that produces/consumes these types — not touching the
orchestration logic.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ChangedFile:
    filename: str
    patch: str | None


@dataclass(frozen=True)
class NormalizedComment:
    path: str
    line: int
    body: str
    old_line: int | None = None


@runtime_checkable
class VCSProvider(Protocol):
    def fetch_pr_files(self) -> list[ChangedFile]: ...

    def post_review(self, summary: str, comments: list[NormalizedComment]) -> dict: ...
