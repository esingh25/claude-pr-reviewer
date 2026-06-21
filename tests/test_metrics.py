import json
from datetime import UTC, datetime

from ai_pr_reviewer.config import Config
from ai_pr_reviewer.metrics import (
    build_metrics_record,
    render_step_summary,
    write_github_output,
    write_step_summary,
)
from ai_pr_reviewer.review_engine import ReviewResult


def _config():
    return Config(
        github_token="gh-token",
        anthropic_api_key="anthropic-key",
        repo_owner="esingh25",
        repo_name="claude-pr-reviewer",
        pr_number=42,
        base_sha="abc1234",
        head_sha="def5678",
        model="claude-sonnet-4-6",
        max_diff_chars=12000,
        max_files=50,
        workspace_root=".",
        enable_cross_file_context=True,
    )


def test_build_metrics_record_includes_expected_fields():
    result = ReviewResult(
        files_reviewed=3,
        comments_posted=2,
        severity_counts={"critical": 1, "high": 1, "medium": 0, "low": 0},
    )
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)

    record = build_metrics_record(_config(), result, duration_seconds=4.5678, now=fixed_now)

    assert record.repo == "esingh25/claude-pr-reviewer"
    assert record.pr_number == 42
    assert record.head_sha == "def5678"
    assert record.model == "claude-sonnet-4-6"
    assert record.files_reviewed == 3
    assert record.comments_posted == 2
    assert record.severity_counts == {"critical": 1, "high": 1, "medium": 0, "low": 0}
    assert record.duration_seconds == 4.568
    assert record.timestamp == fixed_now.isoformat()


def test_render_step_summary_includes_key_numbers():
    result = ReviewResult(
        files_reviewed=2,
        comments_posted=1,
        severity_counts={"critical": 0, "high": 1, "medium": 0, "low": 0},
    )
    record = build_metrics_record(_config(), result, duration_seconds=1.0)

    summary = render_step_summary(record)

    assert "esingh25/claude-pr-reviewer" in summary
    assert "#42" in summary
    assert "Files reviewed:** 2" in summary
    assert "Comments posted:** 1" in summary
    assert "high: 1" in summary


def test_write_github_output_appends_single_line_json(tmp_path):
    output_path = tmp_path / "output.txt"
    record = build_metrics_record(
        _config(), ReviewResult(files_reviewed=1, comments_posted=0), duration_seconds=0.5
    )

    write_github_output(record, str(output_path))

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("metrics=")
    parsed = json.loads(lines[0].removeprefix("metrics="))
    assert parsed["pr_number"] == 42


def test_write_github_output_noop_when_path_is_none():
    record = build_metrics_record(
        _config(), ReviewResult(files_reviewed=1, comments_posted=0), duration_seconds=0.5
    )

    write_github_output(record, None)


def test_write_step_summary_appends_without_overwriting(tmp_path):
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("# Existing content\n")

    write_step_summary("New section\n", str(summary_path))

    content = summary_path.read_text(encoding="utf-8")
    assert "# Existing content" in content
    assert "New section" in content


def test_write_step_summary_noop_when_path_is_none():
    write_step_summary("text", None)


def test_build_metrics_record_defaults_status_to_success():
    record = build_metrics_record(
        _config(), ReviewResult(files_reviewed=1, comments_posted=0), duration_seconds=0.5
    )

    assert record.status == "success"


def test_build_metrics_record_honors_explicit_status():
    record = build_metrics_record(
        _config(),
        ReviewResult(files_reviewed=0, comments_posted=0),
        duration_seconds=0.1,
        status="error",
    )

    assert record.status == "error"


def test_render_step_summary_includes_status():
    record = build_metrics_record(
        _config(),
        ReviewResult(files_reviewed=0, comments_posted=0),
        duration_seconds=0.1,
        status="error",
    )

    assert "error" in render_step_summary(record).lower()


def test_write_github_output_logs_warning_instead_of_raising_on_oserror(tmp_path, capsys):
    unwritable_path = tmp_path / "missing-dir" / "output.txt"
    record = build_metrics_record(
        _config(), ReviewResult(files_reviewed=1, comments_posted=0), duration_seconds=0.5
    )

    write_github_output(record, str(unwritable_path))

    assert "::warning::" in capsys.readouterr().err


def test_write_step_summary_logs_warning_instead_of_raising_on_oserror(tmp_path, capsys):
    unwritable_path = tmp_path / "missing-dir" / "summary.md"

    write_step_summary("text", str(unwritable_path))

    assert "::warning::" in capsys.readouterr().err
