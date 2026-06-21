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


def test_main_writes_metrics_output_and_step_summary(tmp_path, monkeypatch):
    from ai_pr_reviewer.__main__ import main

    output_path = tmp_path / "output.txt"
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    with (
        patch("ai_pr_reviewer.__main__.load_config", return_value=_config()),
        patch("ai_pr_reviewer.__main__.GitHubClient"),
        patch("ai_pr_reviewer.__main__.anthropic.Anthropic"),
        patch(
            "ai_pr_reviewer.__main__.run_review",
            return_value=ReviewResult(
                files_reviewed=2,
                comments_posted=1,
                severity_counts={"critical": 0, "high": 1, "medium": 0, "low": 0},
            ),
        ),
    ):
        exit_code = main()

    assert exit_code == 0
    output_content = output_path.read_text(encoding="utf-8")
    assert output_content.startswith("metrics=")
    assert '"pr_number":42' in output_content
    summary_content = summary_path.read_text(encoding="utf-8")
    assert "Claude PR Review Metrics" in summary_content
    assert "Files reviewed:** 2" in summary_content


def test_main_skips_metrics_output_when_env_vars_unset(monkeypatch):
    from ai_pr_reviewer.__main__ import main

    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    with (
        patch("ai_pr_reviewer.__main__.load_config", return_value=_config()),
        patch("ai_pr_reviewer.__main__.GitHubClient"),
        patch("ai_pr_reviewer.__main__.anthropic.Anthropic"),
        patch(
            "ai_pr_reviewer.__main__.run_review",
            return_value=ReviewResult(files_reviewed=1, comments_posted=0),
        ),
    ):
        exit_code = main()

    assert exit_code == 0


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


def test_main_emits_error_status_metrics_on_github_api_failure(tmp_path, monkeypatch):
    from ai_pr_reviewer.__main__ import main

    output_path = tmp_path / "output.txt"
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

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
    assert '"status":"error"' in output_path.read_text(encoding="utf-8")
    assert "error" in summary_path.read_text(encoding="utf-8").lower()
