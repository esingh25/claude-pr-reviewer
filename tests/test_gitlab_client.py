import json

import pytest
import responses

from ai_pr_reviewer.gitlab_client import GitLabClient, GitLabClientError, GitLabProvider
from ai_pr_reviewer.vcs_provider import NormalizedComment, VCSProvider

PROJECT_ID = "mygroup/myproject"
PROJECT_ID_ENCODED = "mygroup%2Fmyproject"
MR_IID = 7
TOKEN = "gitlab-token-123"
API_BASE = f"https://gitlab.com/api/v4/projects/{PROJECT_ID_ENCODED}"


@pytest.fixture
def client():
    return GitLabClient(token=TOKEN, project_id=PROJECT_ID)


@responses.activate
def test_fetch_mr_diffs_returns_single_page(client):
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}/diffs",
        json=[{"old_path": "foo.py", "new_path": "foo.py", "diff": "@@ -1 +1 @@\n-a\n+b"}],
        status=200,
    )

    diffs = client.fetch_mr_diffs(MR_IID)

    assert diffs == [{"old_path": "foo.py", "new_path": "foo.py", "diff": "@@ -1 +1 @@\n-a\n+b"}]
    assert responses.calls[0].request.headers["PRIVATE-TOKEN"] == TOKEN


@responses.activate
def test_fetch_mr_diffs_follows_pagination(client):
    page_1 = [{"old_path": f"f{i}.py", "new_path": f"f{i}.py", "diff": ""} for i in range(100)]
    page_2 = [{"old_path": "last.py", "new_path": "last.py", "diff": "+x"}]

    responses.get(f"{API_BASE}/merge_requests/{MR_IID}/diffs", json=page_1, status=200)
    responses.get(f"{API_BASE}/merge_requests/{MR_IID}/diffs", json=page_2, status=200)

    diffs = client.fetch_mr_diffs(MR_IID)

    assert len(diffs) == 101
    assert diffs[-1]["new_path"] == "last.py"


@responses.activate
def test_fetch_mr_diffs_raises_on_error_status(client):
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}/diffs", json={"message": "Not Found"}, status=404
    )

    with pytest.raises(GitLabClientError, match="404"):
        client.fetch_mr_diffs(MR_IID)


@responses.activate
def test_fetch_diff_refs_returns_shas(client):
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}",
        json={"diff_refs": {"base_sha": "base123", "start_sha": "start123", "head_sha": "head123"}},
        status=200,
    )

    diff_refs = client.fetch_diff_refs(MR_IID)

    assert diff_refs == {"base_sha": "base123", "start_sha": "start123", "head_sha": "head123"}


@responses.activate
def test_fetch_diff_refs_raises_when_missing(client):
    responses.get(f"{API_BASE}/merge_requests/{MR_IID}", json={}, status=200)

    with pytest.raises(GitLabClientError, match="diff_refs"):
        client.fetch_diff_refs(MR_IID)


@responses.activate
def test_post_note_sends_body(client):
    captured = responses.post(
        f"{API_BASE}/merge_requests/{MR_IID}/notes", json={"id": 1}, status=201
    )

    result = client.post_note(MR_IID, "Looks good overall.")

    assert result == {"id": 1}
    sent_body = json.loads(captured.calls[0].request.body)
    assert sent_body == {"body": "Looks good overall."}


@responses.activate
def test_post_note_raises_on_error_status(client):
    responses.post(
        f"{API_BASE}/merge_requests/{MR_IID}/notes", json={"message": "Forbidden"}, status=403
    )

    with pytest.raises(GitLabClientError, match="403"):
        client.post_note(MR_IID, "x")


@responses.activate
def test_post_discussion_sends_body_and_position(client):
    captured = responses.post(
        f"{API_BASE}/merge_requests/{MR_IID}/discussions", json={"id": "abc"}, status=201
    )
    position = {
        "position_type": "text",
        "base_sha": "base123",
        "start_sha": "start123",
        "head_sha": "head123",
        "old_path": "foo.py",
        "new_path": "foo.py",
        "new_line": 5,
    }

    result = client.post_discussion(MR_IID, "Fix this.", position)

    assert result == {"id": "abc"}
    sent_body = json.loads(captured.calls[0].request.body)
    assert sent_body == {"body": "Fix this.", "position": position}


@responses.activate
def test_post_discussion_raises_on_error_status(client):
    responses.post(
        f"{API_BASE}/merge_requests/{MR_IID}/discussions",
        json={"message": "Unprocessable"},
        status=422,
    )

    with pytest.raises(GitLabClientError, match="422"):
        client.post_discussion(MR_IID, "x", {})


def test_gitlab_provider_satisfies_vcs_provider_protocol(client):
    provider = GitLabProvider(client, MR_IID)

    assert isinstance(provider, VCSProvider)


@responses.activate
def test_gitlab_provider_fetch_pr_files_normalizes_to_changed_file(client):
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}/diffs",
        json=[{"old_path": "foo.py", "new_path": "foo.py", "diff": "@@ -1 +1 @@\n-a\n+b"}],
        status=200,
    )
    provider = GitLabProvider(client, MR_IID)

    files = provider.fetch_pr_files()

    assert len(files) == 1
    assert files[0].filename == "foo.py"
    assert files[0].patch == "@@ -1 +1 @@\n-a\n+b"


@responses.activate
def test_gitlab_provider_fetch_pr_files_falls_back_to_old_path_for_deleted_files(client):
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}/diffs",
        json=[{"old_path": "removed.py", "new_path": "", "diff": "@@ -1 +0 @@\n-a"}],
        status=200,
    )
    provider = GitLabProvider(client, MR_IID)

    files = provider.fetch_pr_files()

    assert files[0].filename == "removed.py"


@responses.activate
def test_gitlab_provider_fetch_pr_files_raises_when_both_paths_missing(client):
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}/diffs",
        json=[{"diff": "@@ -1 +1 @@\n-a\n+b"}],
        status=200,
    )
    provider = GitLabProvider(client, MR_IID)

    with pytest.raises(GitLabClientError, match="path"):
        provider.fetch_pr_files()


@responses.activate
def test_gitlab_provider_post_review_posts_note_and_discussion_with_shas(client):
    responses.post(f"{API_BASE}/merge_requests/{MR_IID}/notes", json={"id": 1}, status=201)
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}",
        json={"diff_refs": {"base_sha": "base123", "start_sha": "start123", "head_sha": "head123"}},
        status=200,
    )
    captured_discussion = responses.post(
        f"{API_BASE}/merge_requests/{MR_IID}/discussions", json={"id": "d1"}, status=201
    )
    provider = GitLabProvider(client, MR_IID)
    comments = [NormalizedComment(path="foo.py", line=5, body="fix this")]

    result = provider.post_review("Summary text", comments)

    assert result == {"note": {"id": 1}, "discussions": [{"id": "d1"}]}
    sent_body = json.loads(captured_discussion.calls[0].request.body)
    assert sent_body["body"] == "fix this"
    assert sent_body["position"] == {
        "position_type": "text",
        "base_sha": "base123",
        "start_sha": "start123",
        "head_sha": "head123",
        "old_path": "foo.py",
        "new_path": "foo.py",
        "new_line": 5,
    }


@responses.activate
def test_gitlab_provider_post_review_includes_old_line_for_context_comments(client):
    responses.post(f"{API_BASE}/merge_requests/{MR_IID}/notes", json={"id": 1}, status=201)
    responses.get(
        f"{API_BASE}/merge_requests/{MR_IID}",
        json={"diff_refs": {"base_sha": "base123", "start_sha": "start123", "head_sha": "head123"}},
        status=200,
    )
    captured_discussion = responses.post(
        f"{API_BASE}/merge_requests/{MR_IID}/discussions", json={"id": "d1"}, status=201
    )
    provider = GitLabProvider(client, MR_IID)
    comments = [NormalizedComment(path="foo.py", line=5, body="context comment", old_line=3)]

    provider.post_review("Summary text", comments)

    sent_body = json.loads(captured_discussion.calls[0].request.body)
    assert sent_body["position"]["new_line"] == 5
    assert sent_body["position"]["old_line"] == 3


@responses.activate
def test_gitlab_provider_post_review_skips_diff_refs_fetch_when_no_comments(client):
    responses.post(f"{API_BASE}/merge_requests/{MR_IID}/notes", json={"id": 1}, status=201)

    result = GitLabProvider(client, MR_IID).post_review("No issues found.", [])

    assert result == {"note": {"id": 1}, "discussions": []}
    assert len(responses.calls) == 1
