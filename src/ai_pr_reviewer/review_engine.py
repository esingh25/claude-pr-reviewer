"""Orchestrate fetching a PR's diff, reviewing each file with Claude, and posting the review."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ai_pr_reviewer.claude_client import ClaudeReviewError, ReviewSuggestion
from ai_pr_reviewer.config import Config
from ai_pr_reviewer.context_finder import RelatedFile, find_related_files
from ai_pr_reviewer.diff_parser import parse_patch
from ai_pr_reviewer.github_client import GitHubClient, ReviewComment

ReviewFn = Callable[[str, str, list[RelatedFile]], list[ReviewSuggestion]]

DISCLAIMER = "_AI-generated review via Claude — verify suggestions before acting on them._\n\n"


@dataclass(frozen=True)
class ReviewResult:
    files_reviewed: int
    comments_posted: int


def _build_summary(files_reviewed: int, comments_posted: int) -> str:
    if comments_posted == 0:
        body = f"Claude reviewed {files_reviewed} file(s) and found no issues."
    else:
        body = f"Claude reviewed {files_reviewed} file(s) and left {comments_posted} comment(s)."
    return DISCLAIMER + body


def run_review(config: Config, github_client: GitHubClient, review_fn: ReviewFn) -> ReviewResult:
    files = github_client.fetch_pr_files(config.pr_number)[: config.max_files]
    all_filenames = [file["filename"] for file in files if file.get("filename")]
    workspace_root = Path(config.workspace_root)

    comments: list[ReviewComment] = []
    files_reviewed = 0

    for file in files:
        patch = file.get("patch")
        if not patch:
            continue

        filename = file["filename"]
        commentable_lines = parse_patch(filename, patch).commentable_lines()
        diff_text = patch[: config.max_diff_chars]
        files_reviewed += 1

        related_files = (
            find_related_files(
                target_filename=filename,
                target_diff_text=diff_text,
                other_filenames=all_filenames,
                workspace_root=workspace_root,
            )
            if config.enable_cross_file_context
            else []
        )

        try:
            suggestions = review_fn(filename, diff_text, related_files)
        except ClaudeReviewError as exc:
            print(f"::warning::Claude review failed for {filename}: {exc}", file=sys.stderr)
            continue

        for suggestion in suggestions:
            if suggestion.line not in commentable_lines:
                continue
            comments.append(
                ReviewComment(
                    path=filename,
                    line=suggestion.line,
                    side="RIGHT",
                    body=f"**{suggestion.severity.upper()}**: {suggestion.comment}",
                )
            )

    if files_reviewed == 0:
        return ReviewResult(files_reviewed=0, comments_posted=0)

    github_client.post_review(
        config.pr_number,
        summary=_build_summary(files_reviewed, len(comments)),
        comments=comments,
    )
    return ReviewResult(files_reviewed=files_reviewed, comments_posted=len(comments))
