"""Process entrypoint for the Claude PR reviewer GitHub Action."""

import os
import sys
import time

import anthropic

from ai_pr_reviewer.claude_client import review_file_diff
from ai_pr_reviewer.config import ConfigError, load_config
from ai_pr_reviewer.context_finder import RelatedFile
from ai_pr_reviewer.github_client import GitHubClient, GitHubClientError
from ai_pr_reviewer.metrics import (
    build_metrics_record,
    render_step_summary,
    write_github_output,
    write_step_summary,
)
from ai_pr_reviewer.review_engine import ReviewResult, run_review


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    github_client = GitHubClient(config.github_token, config.repo_owner, config.repo_name)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    def review_fn(filename: str, diff_text: str, related_files: list[RelatedFile]):
        return review_file_diff(
            anthropic_client, config.model, filename, diff_text, related_files=related_files
        )

    started_at = time.monotonic()
    try:
        result = run_review(config, github_client, review_fn)
    except GitHubClientError as exc:
        duration_seconds = time.monotonic() - started_at
        failure_record = build_metrics_record(
            config,
            ReviewResult(files_reviewed=0, comments_posted=0),
            duration_seconds,
            status="error",
        )
        write_github_output(failure_record, os.environ.get("GITHUB_OUTPUT"))
        write_step_summary(
            render_step_summary(failure_record), os.environ.get("GITHUB_STEP_SUMMARY")
        )
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    duration_seconds = time.monotonic() - started_at

    record = build_metrics_record(config, result, duration_seconds)
    write_github_output(record, os.environ.get("GITHUB_OUTPUT"))
    write_step_summary(render_step_summary(record), os.environ.get("GITHUB_STEP_SUMMARY"))

    print(f"Reviewed {result.files_reviewed} file(s), posted {result.comments_posted} comment(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
