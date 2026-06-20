from unittest.mock import patch

from ai_pr_reviewer.config import Config, ConfigError
from ai_pr_reviewer.context_finder import RelatedFile
from ai_pr_reviewer.github_client import GitHubClientError
from ai_pr_reviewer.review_engine import ReviewResult


def _config():
    return Config(
        github_token="gh-token",
        anthropic_api_key="anthropic-key",
        repo_owner="esingh25",
        repo_name="claude-pr-reviewer",
        pr_number=42,
        base_sha="abc",
        head_sha="def",
        model="claude-sonnet-4-6",
        max_diff_chars=12000,
        max_files=50,
        workspace_root=".",
        enable_cross_file_context=True,
    )


def test_main_returns_1_and_logs_error_when_config_invalid():
    from ai_pr_reviewer.__main__ import main

    with patch(
        "ai_pr_reviewer.__main__.load_config", side_effect=ConfigError("GITHUB_TOKEN missing")
    ):
        exit_code = main()

    assert exit_code == 1


def test_main_returns_0_and_runs_review_when_config_valid():
    from ai_pr_reviewer.__main__ import main

    with (
        patch("ai_pr_reviewer.__main__.load_config", return_value=_config()),
        patch("ai_pr_reviewer.__main__.GitHubClient") as mock_github_client_cls,
        patch("ai_pr_reviewer.__main__.anthropic.Anthropic") as mock_anthropic_cls,
        patch(
            "ai_pr_reviewer.__main__.run_review",
            return_value=ReviewResult(files_reviewed=2, comments_posted=1),
        ) as mock_run_review,
    ):
        exit_code = main()

    assert exit_code == 0
    mock_github_client_cls.assert_called_once_with("gh-token", "esingh25", "claude-pr-reviewer")
    mock_anthropic_cls.assert_called_once_with(api_key="anthropic-key")
    mock_run_review.assert_called_once()


def test_main_review_fn_closure_forwards_related_files_to_claude_client():
    from ai_pr_reviewer.__main__ import main

    with (
        patch("ai_pr_reviewer.__main__.load_config", return_value=_config()),
        patch("ai_pr_reviewer.__main__.GitHubClient"),
        patch("ai_pr_reviewer.__main__.anthropic.Anthropic"),
        patch(
            "ai_pr_reviewer.__main__.run_review",
            return_value=ReviewResult(files_reviewed=1, comments_posted=0),
        ) as mock_run_review,
        patch("ai_pr_reviewer.__main__.review_file_diff", return_value=[]) as mock_review_file_diff,
    ):
        main()
        review_fn = mock_run_review.call_args[0][2]
        related = [RelatedFile(filename="config.py", excerpt="class Config: pass")]
        review_fn("main.py", "diff text", related)

    mock_review_file_diff.assert_called_once_with(
        mock_review_file_diff.call_args[0][0],
        "claude-sonnet-4-6",
        "main.py",
        "diff text",
        related_files=related,
    )


def test_main_returns_1_and_logs_error_when_github_api_fails():
    from ai_pr_reviewer.__main__ import main

    with (
        patch("ai_pr_reviewer.__main__.load_config", return_value=_config()),
        patch("ai_pr_reviewer.__main__.GitHubClient"),
        patch("ai_pr_reviewer.__main__.anthropic.Anthropic"),
        patch(
            "ai_pr_reviewer.__main__.run_review",
            side_effect=GitHubClientError("GitHub API request failed with 422"),
        ),
    ):
        exit_code = main()

    assert exit_code == 1
