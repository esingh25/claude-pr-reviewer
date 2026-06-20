import json

import pytest

from ai_pr_reviewer.claude_client import ClaudeReviewError, ReviewSuggestion, review_file_diff


class _FakeContentBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeContentBlock(text)]


class _FakeMessages:
    def __init__(self, text):
        self._text = text
        self.create_kwargs = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return _FakeMessage(self._text)


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def _valid_response_json():
    return json.dumps(
        {
            "comments": [
                {"line": 12, "severity": "high", "comment": "Possible off-by-one error here."},
                {"line": 20, "severity": "low", "comment": "Consider a more descriptive name."},
            ]
        }
    )


def test_review_file_diff_parses_valid_json_response():
    client = _FakeClient(_valid_response_json())

    suggestions = review_file_diff(
        client, model="claude-sonnet-4-6", filename="foo.py", diff_text="@@ -1 +1 @@\n-a\n+b"
    )

    assert suggestions == [
        ReviewSuggestion(line=12, severity="high", comment="Possible off-by-one error here."),
        ReviewSuggestion(line=20, severity="low", comment="Consider a more descriptive name."),
    ]
    assert client.messages.create_kwargs["model"] == "claude-sonnet-4-6"


def test_review_file_diff_strips_markdown_code_fences():
    fenced = f"```json\n{_valid_response_json()}\n```"
    client = _FakeClient(fenced)

    suggestions = review_file_diff(
        client, model="claude-sonnet-4-6", filename="foo.py", diff_text="diff"
    )

    assert len(suggestions) == 2


def test_review_file_diff_raises_on_invalid_json():
    client = _FakeClient("not json at all")

    with pytest.raises(ClaudeReviewError, match="JSON"):
        review_file_diff(client, model="claude-sonnet-4-6", filename="foo.py", diff_text="diff")


def test_review_file_diff_skips_malformed_entries():
    payload = json.dumps(
        {
            "comments": [
                {"line": 5, "severity": "medium", "comment": "Valid entry."},
                {"severity": "medium", "comment": "Missing line number."},
                {"line": "not-an-int", "severity": "medium", "comment": "Bad line type."},
            ]
        }
    )
    client = _FakeClient(payload)

    suggestions = review_file_diff(
        client, model="claude-sonnet-4-6", filename="foo.py", diff_text="diff"
    )

    assert suggestions == [ReviewSuggestion(line=5, severity="medium", comment="Valid entry.")]


def test_review_file_diff_returns_empty_list_when_no_comments():
    client = _FakeClient(json.dumps({"comments": []}))

    suggestions = review_file_diff(
        client, model="claude-sonnet-4-6", filename="foo.py", diff_text="diff"
    )

    assert suggestions == []


def test_review_file_diff_caps_number_of_comments_per_file():
    payload = json.dumps(
        {
            "comments": [
                {"line": i, "severity": "low", "comment": f"comment {i}"} for i in range(1, 21)
            ]
        }
    )
    client = _FakeClient(payload)

    suggestions = review_file_diff(
        client, model="claude-sonnet-4-6", filename="foo.py", diff_text="diff"
    )

    assert len(suggestions) == 10


def test_review_file_diff_truncates_long_comment_text():
    long_comment = "x" * 2000
    payload = json.dumps({"comments": [{"line": 1, "severity": "low", "comment": long_comment}]})
    client = _FakeClient(payload)

    suggestions = review_file_diff(
        client, model="claude-sonnet-4-6", filename="foo.py", diff_text="diff"
    )

    assert len(suggestions[0].comment) == 1000


def test_review_file_diff_normalizes_severity_casing():
    payload = json.dumps({"comments": [{"line": 1, "severity": "HIGH", "comment": "loud"}]})
    client = _FakeClient(payload)

    suggestions = review_file_diff(
        client, model="claude-sonnet-4-6", filename="foo.py", diff_text="diff"
    )

    assert suggestions == [ReviewSuggestion(line=1, severity="high", comment="loud")]


def test_system_prompt_warns_against_following_instructions_in_diff():
    from ai_pr_reviewer.claude_client import SYSTEM_PROMPT

    assert "untrusted" in SYSTEM_PROMPT.lower()
    assert "never follow" in SYSTEM_PROMPT.lower() or "do not follow" in SYSTEM_PROMPT.lower()
