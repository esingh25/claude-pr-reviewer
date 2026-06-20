

from ai_pr_reviewer.claude_client import ClaudeReviewError, ReviewSuggestion
from ai_pr_reviewer.config import Config
from ai_pr_reviewer.review_engine import run_review


class _FakeGitHubClient:
    def __init__(self, files):
        self._files = files
        self.post_review_calls = []

    def fetch_pr_files(self, pr_number):
        self.pr_number_requested = pr_number
        return self._files

    def post_review(self, pr_number, summary, comments, event="COMMENT"):
        self.post_review_calls.append(
            {"pr_number": pr_number, "summary": summary, "comments": comments, "event": event}
        )
        return {"id": 1}


def _config(max_diff_chars=12000, max_files=50):
    return Config(
        github_token="gh-token",
        anthropic_api_key="anthropic-key",
        repo_owner="esingh25",
        repo_name="claude-pr-reviewer",
        pr_number=42,
        base_sha="abc",
        head_sha="def",
        model="claude-sonnet-4-6",
        max_diff_chars=max_diff_chars,
        max_files=max_files,
    )


def test_run_review_posts_comments_from_multiple_files():
    files = [
        {"filename": "a.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+added"},
        {"filename": "b.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+added"},
    ]
    github_client = _FakeGitHubClient(files)

    def review_fn(filename, diff_text):
        return [ReviewSuggestion(line=2, severity="medium", comment=f"Issue in {filename}")]

    result = run_review(_config(), github_client, review_fn)

    assert result.files_reviewed == 2
    assert result.comments_posted == 2
    [call] = github_client.post_review_calls
    assert call["pr_number"] == 42
    assert {c.path for c in call["comments"]} == {"a.py", "b.py"}
    assert all(c.line == 2 and c.side == "RIGHT" for c in call["comments"])


def test_run_review_skips_files_without_patch():
    files = [{"filename": "image.png", "status": "modified", "patch": None}]
    github_client = _FakeGitHubClient(files)

    result = run_review(_config(), github_client, lambda filename, diff_text: [])

    assert result.files_reviewed == 0
    assert result.comments_posted == 0
    assert github_client.post_review_calls == []


def test_run_review_filters_suggestions_outside_diff():
    files = [{"filename": "a.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+added"}]
    github_client = _FakeGitHubClient(files)

    def review_fn(filename, diff_text):
        return [
            ReviewSuggestion(line=2, severity="medium", comment="valid, on added line"),
            ReviewSuggestion(line=999, severity="medium", comment="invalid, not in diff"),
        ]

    result = run_review(_config(), github_client, review_fn)

    assert result.comments_posted == 1
    [call] = github_client.post_review_calls
    assert len(call["comments"]) == 1
    assert call["comments"][0].line == 2


def test_run_review_continues_when_one_file_review_fails():
    files = [
        {"filename": "broken.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+added"},
        {"filename": "ok.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+added"},
    ]
    github_client = _FakeGitHubClient(files)

    def review_fn(filename, diff_text):
        if filename == "broken.py":
            raise ClaudeReviewError("bad response")
        return [ReviewSuggestion(line=2, severity="low", comment="fine")]

    result = run_review(_config(), github_client, review_fn)

    assert result.files_reviewed == 2
    assert result.comments_posted == 1
    [call] = github_client.post_review_calls
    assert call["comments"][0].path == "ok.py"


def test_run_review_posts_no_issues_summary_when_no_comments():
    files = [{"filename": "a.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+added"}]
    github_client = _FakeGitHubClient(files)

    result = run_review(_config(), github_client, lambda filename, diff_text: [])

    assert result.comments_posted == 0
    [call] = github_client.post_review_calls
    assert "no issues" in call["summary"].lower()


def test_run_review_skips_posting_when_no_files_changed():
    github_client = _FakeGitHubClient([])

    result = run_review(_config(), github_client, lambda filename, diff_text: [])

    assert result == type(result)(files_reviewed=0, comments_posted=0)
    assert github_client.post_review_calls == []


def test_run_review_truncates_diff_to_max_chars():
    long_patch = "@@ -1,1 +1,1 @@\n+" + ("x" * 100)
    files = [{"filename": "a.py", "status": "modified", "patch": long_patch}]
    github_client = _FakeGitHubClient(files)
    seen = {}

    def review_fn(filename, diff_text):
        seen["diff_text"] = diff_text
        return []

    run_review(_config(max_diff_chars=20), github_client, review_fn)

    assert len(seen["diff_text"]) == 20


def test_run_review_caps_files_reviewed_at_max_files():
    files = [
        {"filename": f"file{i}.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+x"}
        for i in range(5)
    ]
    github_client = _FakeGitHubClient(files)

    result = run_review(_config(max_files=2), github_client, lambda filename, diff_text: [])

    assert result.files_reviewed == 2


def test_run_review_logs_warning_when_file_review_fails(capsys):
    patch_text = "@@ -1,1 +1,2 @@\n line1\n+x"
    files = [{"filename": "broken.py", "status": "modified", "patch": patch_text}]
    github_client = _FakeGitHubClient(files)

    def review_fn(filename, diff_text):
        raise ClaudeReviewError("bad response")

    run_review(_config(), github_client, review_fn)

    captured = capsys.readouterr()
    assert "broken.py" in captured.err
    assert "::warning::" in captured.err


def test_run_review_summary_includes_ai_disclaimer():
    files = [{"filename": "a.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n line1\n+added"}]
    github_client = _FakeGitHubClient(files)

    run_review(_config(), github_client, lambda filename, diff_text: [])

    [call] = github_client.post_review_calls
    assert "ai-generated" in call["summary"].lower()
