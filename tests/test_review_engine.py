from ai_pr_reviewer.claude_client import ClaudeReviewError, ReviewSuggestion
from ai_pr_reviewer.config import Config
from ai_pr_reviewer.review_engine import run_review
from ai_pr_reviewer.vcs_provider import ChangedFile


class _FakeVCSProvider:
    def __init__(self, files):
        self._files = files
        self.post_review_calls = []

    def fetch_pr_files(self):
        return self._files

    def post_review(self, summary, comments):
        self.post_review_calls.append({"summary": summary, "comments": comments})
        return {"id": 1}


def _config(max_diff_chars=12000, max_files=50, workspace_root=".", enable_cross_file_context=True):
    return Config(
        provider="github",
        vcs_token="gh-token",
        anthropic_api_key="anthropic-key",
        repo_owner="esingh25",
        repo_name="claude-pr-reviewer",
        pr_number=42,
        base_sha="abc1234567890abc1234567890abc1234567890a",
        head_sha="def4567890123def4567890123def4567890123d",
        model="claude-sonnet-4-6",
        max_diff_chars=max_diff_chars,
        max_files=max_files,
        workspace_root=workspace_root,
        enable_cross_file_context=enable_cross_file_context,
        gitlab_base_url="https://gitlab.com",
    )


def test_run_review_posts_comments_from_multiple_files():
    files = [
        ChangedFile(filename="a.py", patch="@@ -1,1 +1,2 @@\n line1\n+added"),
        ChangedFile(filename="b.py", patch="@@ -1,1 +1,2 @@\n line1\n+added"),
    ]
    provider = _FakeVCSProvider(files)

    def review_fn(filename, diff_text, related_files):
        return [ReviewSuggestion(line=2, severity="medium", comment=f"Issue in {filename}")]

    result = run_review(_config(), provider, review_fn)

    assert result.files_reviewed == 2
    assert result.comments_posted == 2
    [call] = provider.post_review_calls
    assert {c.path for c in call["comments"]} == {"a.py", "b.py"}
    assert all(c.line == 2 for c in call["comments"])


def test_run_review_skips_files_without_patch():
    files = [ChangedFile(filename="image.png", patch=None)]
    provider = _FakeVCSProvider(files)

    result = run_review(_config(), provider, lambda filename, diff_text, related_files: [])

    assert result.files_reviewed == 0
    assert result.comments_posted == 0
    assert provider.post_review_calls == []


def test_run_review_filters_suggestions_outside_diff():
    files = [ChangedFile(filename="a.py", patch="@@ -1,1 +1,2 @@\n line1\n+added")]
    provider = _FakeVCSProvider(files)

    def review_fn(filename, diff_text, related_files):
        return [
            ReviewSuggestion(line=2, severity="medium", comment="valid, on added line"),
            ReviewSuggestion(line=999, severity="medium", comment="invalid, not in diff"),
        ]

    result = run_review(_config(), provider, review_fn)

    assert result.comments_posted == 1
    [call] = provider.post_review_calls
    assert len(call["comments"]) == 1
    assert call["comments"][0].line == 2


def test_run_review_continues_when_one_file_review_fails():
    files = [
        ChangedFile(filename="broken.py", patch="@@ -1,1 +1,2 @@\n line1\n+added"),
        ChangedFile(filename="ok.py", patch="@@ -1,1 +1,2 @@\n line1\n+added"),
    ]
    provider = _FakeVCSProvider(files)

    def review_fn(filename, diff_text, related_files):
        if filename == "broken.py":
            raise ClaudeReviewError("bad response")
        return [ReviewSuggestion(line=2, severity="low", comment="fine")]

    result = run_review(_config(), provider, review_fn)

    assert result.files_reviewed == 2
    assert result.comments_posted == 1
    [call] = provider.post_review_calls
    assert call["comments"][0].path == "ok.py"


def test_run_review_posts_no_issues_summary_when_no_comments():
    files = [ChangedFile(filename="a.py", patch="@@ -1,1 +1,2 @@\n line1\n+added")]
    provider = _FakeVCSProvider(files)

    result = run_review(_config(), provider, lambda filename, diff_text, related_files: [])

    assert result.comments_posted == 0
    [call] = provider.post_review_calls
    assert "no issues" in call["summary"].lower()


def test_run_review_skips_posting_when_no_files_changed():
    provider = _FakeVCSProvider([])

    result = run_review(_config(), provider, lambda filename, diff_text, related_files: [])

    assert result == type(result)(files_reviewed=0, comments_posted=0)
    assert provider.post_review_calls == []


def test_run_review_truncates_diff_to_max_chars():
    long_patch = "@@ -1,1 +1,1 @@\n+" + ("x" * 100)
    files = [ChangedFile(filename="a.py", patch=long_patch)]
    provider = _FakeVCSProvider(files)
    seen = {}

    def review_fn(filename, diff_text, related_files):
        seen["diff_text"] = diff_text
        return []

    run_review(_config(max_diff_chars=20), provider, review_fn)

    assert len(seen["diff_text"]) == 20


def test_run_review_caps_files_reviewed_at_max_files():
    files = [
        ChangedFile(filename=f"file{i}.py", patch="@@ -1,1 +1,2 @@\n line1\n+x") for i in range(5)
    ]
    provider = _FakeVCSProvider(files)

    def no_op_review_fn(filename, diff_text, related_files):
        return []

    result = run_review(_config(max_files=2), provider, no_op_review_fn)

    assert result.files_reviewed == 2


def test_run_review_logs_warning_when_file_review_fails(capsys):
    patch_text = "@@ -1,1 +1,2 @@\n line1\n+x"
    files = [ChangedFile(filename="broken.py", patch=patch_text)]
    provider = _FakeVCSProvider(files)

    def review_fn(filename, diff_text, related_files):
        raise ClaudeReviewError("bad response")

    run_review(_config(), provider, review_fn)

    captured = capsys.readouterr()
    assert "broken.py" in captured.err
    assert "::warning::" in captured.err


def test_run_review_passes_related_files_to_review_fn(tmp_path):
    (tmp_path / "config.py").write_text("class Config:\n    pass\n")
    files = [
        ChangedFile(
            filename="main.py", patch="@@ -1,1 +1,2 @@\n line1\n+from config import Config"
        ),
        ChangedFile(filename="config.py", patch="@@ -1,1 +1,2 @@\n line1\n+x"),
    ]
    provider = _FakeVCSProvider(files)
    seen = {}

    def review_fn(filename, diff_text, related_files):
        if filename == "main.py":
            seen["related_files"] = related_files
        return []

    run_review(_config(workspace_root=str(tmp_path)), provider, review_fn)

    assert len(seen["related_files"]) == 1
    assert seen["related_files"][0].filename == "config.py"


def test_run_review_skips_cross_file_context_when_disabled(tmp_path):
    (tmp_path / "config.py").write_text("class Config:\n    pass\n")
    files = [
        ChangedFile(
            filename="main.py", patch="@@ -1,1 +1,2 @@\n line1\n+from config import Config"
        ),
        ChangedFile(filename="config.py", patch="@@ -1,1 +1,2 @@\n line1\n+x"),
    ]
    provider = _FakeVCSProvider(files)
    seen = {}

    def review_fn(filename, diff_text, related_files):
        if filename == "main.py":
            seen["related_files"] = related_files
        return []

    run_review(
        _config(workspace_root=str(tmp_path), enable_cross_file_context=False),
        provider,
        review_fn,
    )

    assert seen["related_files"] == []


def test_run_review_populates_old_line_for_context_line_comments():
    patch = "@@ -1,3 +1,3 @@\n line1\n-removed\n+added\n line3"
    files = [ChangedFile(filename="a.py", patch=patch)]
    provider = _FakeVCSProvider(files)

    def review_fn(filename, diff_text, related_files):
        return [ReviewSuggestion(line=3, severity="low", comment="context line comment")]

    run_review(_config(), provider, review_fn)

    [call] = provider.post_review_calls
    assert call["comments"][0].line == 3
    assert call["comments"][0].old_line == 3


def test_run_review_leaves_old_line_none_for_added_line_comments():
    files = [ChangedFile(filename="a.py", patch="@@ -1,1 +1,2 @@\n line1\n+added")]
    provider = _FakeVCSProvider(files)

    def review_fn(filename, diff_text, related_files):
        return [ReviewSuggestion(line=2, severity="low", comment="added line comment")]

    run_review(_config(), provider, review_fn)

    [call] = provider.post_review_calls
    assert call["comments"][0].old_line is None


def test_run_review_tracks_severity_counts_of_posted_comments():
    files = [ChangedFile(filename="a.py", patch="@@ -1,1 +1,3 @@\n line1\n+x\n+y")]
    provider = _FakeVCSProvider(files)

    def review_fn(filename, diff_text, related_files):
        return [
            ReviewSuggestion(line=2, severity="critical", comment="bad"),
            ReviewSuggestion(line=3, severity="critical", comment="also bad"),
            ReviewSuggestion(line=999, severity="high", comment="not in diff, filtered out"),
        ]

    result = run_review(_config(), provider, review_fn)

    assert result.severity_counts == {"critical": 2, "high": 0, "medium": 0, "low": 0}


def test_run_review_severity_counts_all_zero_when_no_comments():
    files = [ChangedFile(filename="a.py", patch="@@ -1,1 +1,2 @@\n line1\n+added")]
    provider = _FakeVCSProvider(files)

    result = run_review(_config(), provider, lambda filename, diff_text, related_files: [])

    assert result.severity_counts == {"critical": 0, "high": 0, "medium": 0, "low": 0}


def test_run_review_summary_includes_ai_disclaimer():
    files = [ChangedFile(filename="a.py", patch="@@ -1,1 +1,2 @@\n line1\n+added")]
    provider = _FakeVCSProvider(files)

    run_review(_config(), provider, lambda filename, diff_text, related_files: [])

    [call] = provider.post_review_calls
    assert "ai-generated" in call["summary"].lower()
