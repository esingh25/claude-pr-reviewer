"""Process entrypoint for the Claude PR reviewer GitHub Action."""

import sys

import anthropic

from ai_pr_reviewer.claude_client import review_file_diff
from ai_pr_reviewer.config import ConfigError, load_config
from ai_pr_reviewer.github_client import GitHubClient, GitHubClientError
from ai_pr_reviewer.review_engine import run_review


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    github_client = GitHubClient(config.github_token, config.repo_owner, config.repo_name)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    def review_fn(filename: str, diff_text: str):
        return review_file_diff(anthropic_client, config.model, filename, diff_text)

    try:
        result = run_review(config, github_client, review_fn)
    except GitHubClientError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    print(f"Reviewed {result.files_reviewed} file(s), posted {result.comments_posted} comment(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
