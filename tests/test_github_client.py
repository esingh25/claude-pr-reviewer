import json

import pytest
import responses

from ai_pr_reviewer.github_client import (
    GitHubClient,
    GitHubClientError,
    ReviewComment,
)

OWNER = "esingh25"
REPO = "claude-pr-reviewer"
PR_NUMBER = 42
TOKEN = "gh-token-123"


@pytest.fixture
def client():
    return GitHubClient(token=TOKEN, owner=OWNER, repo=REPO)


@responses.activate
def test_fetch_pr_files_returns_single_page(client):
    responses.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/files",
        json=[{"filename": "foo.py", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"}],
        status=200,
    )

    files = client.fetch_pr_files(PR_NUMBER)

    assert files == [{"filename": "foo.py", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"}]
    assert responses.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"


@responses.activate
def test_fetch_pr_files_follows_pagination(client):
    page_1 = [{"filename": f"file{i}.py", "status": "modified", "patch": ""} for i in range(100)]
    page_2 = [{"filename": "last.py", "status": "added", "patch": "+x"}]

    responses.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/files",
        json=page_1,
        status=200,
    )
    responses.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/files",
        json=page_2,
        status=200,
    )

    files = client.fetch_pr_files(PR_NUMBER)

    assert len(files) == 101
    assert files[-1]["filename"] == "last.py"
    assert responses.calls[0].request.params["page"] == "1"
    assert responses.calls[1].request.params["page"] == "2"


@responses.activate
def test_fetch_pr_files_raises_on_error_status(client):
    responses.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/files",
        json={"message": "Not Found"},
        status=404,
    )

    with pytest.raises(GitHubClientError, match="404"):
        client.fetch_pr_files(PR_NUMBER)


@responses.activate
def test_post_review_sends_expected_payload(client):
    captured = responses.post(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/reviews",
        json={"id": 1},
        status=200,
    )

    comments = [ReviewComment(path="foo.py", line=2, side="RIGHT", body="Consider renaming this.")]
    result = client.post_review(PR_NUMBER, summary="Looks mostly good.", comments=comments)

    assert result == {"id": 1}
    sent_body = json.loads(captured.calls[0].request.body)
    assert sent_body["body"] == "Looks mostly good."
    assert sent_body["event"] == "COMMENT"
    assert sent_body["comments"] == [
        {"path": "foo.py", "line": 2, "side": "RIGHT", "body": "Consider renaming this."}
    ]


@responses.activate
def test_post_review_raises_on_error_status(client):
    responses.post(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/reviews",
        json={"message": "Unprocessable Entity"},
        status=422,
    )

    with pytest.raises(GitHubClientError, match="422"):
        client.post_review(PR_NUMBER, summary="x", comments=[])
