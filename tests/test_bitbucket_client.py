import json

import pytest
import responses

from ai_pr_reviewer.bitbucket_client import (
    BitbucketClient,
    BitbucketClientError,
    BitbucketProvider,
)
from ai_pr_reviewer.vcs_provider import NormalizedComment, VCSProvider

WORKSPACE = "myworkspace"
REPO_SLUG = "myrepo"
PR_ID = 9
TOKEN = "bb-token-123"
API_BASE = f"https://api.bitbucket.org/2.0/repositories/{WORKSPACE}/{REPO_SLUG}/pullrequests/{PR_ID}"


@pytest.fixture
def client():
    return BitbucketClient(token=TOKEN, workspace=WORKSPACE, repo_slug=REPO_SLUG)


@responses.activate
def test_fetch_diffstat_returns_single_page(client):
    responses.get(
        f"{API_BASE}/diffstat",
        json={
            "values": [
                {"status": "modified", "old": {"path": "foo.py"}, "new": {"path": "foo.py"}}
            ]
        },
        status=200,
    )

    entries = client.fetch_diffstat(PR_ID)

    assert entries == [{"status": "modified", "old": {"path": "foo.py"}, "new": {"path": "foo.py"}}]
    assert responses.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"


@responses.activate
def test_fetch_diffstat_follows_next_page_url(client):
    page_2_url = f"{API_BASE}/diffstat?page=2"
    responses.get(
        f"{API_BASE}/diffstat",
        json={
            "values": [{"status": "added", "old": None, "new": {"path": "a.py"}}],
            "next": page_2_url,
        },
        status=200,
    )
    responses.get(
        page_2_url,
        json={"values": [{"status": "added", "old": None, "new": {"path": "b.py"}}]},
        status=200,
    )

    entries = client.fetch_diffstat(PR_ID)

    assert len(entries) == 2
    assert entries[1]["new"]["path"] == "b.py"


@responses.activate
def test_fetch_diffstat_raises_on_error_status(client):
    responses.get(f"{API_BASE}/diffstat", json={"error": {"message": "Not Found"}}, status=404)

    with pytest.raises(BitbucketClientError, match="404"):
        client.fetch_diffstat(PR_ID)


@responses.activate
def test_fetch_raw_diff_returns_text(client):
    diff_text = "diff --git a/foo.py b/foo.py\n@@ -1 +1 @@\n-a\n+b"
    responses.get(f"{API_BASE}/diff", body=diff_text, status=200)

    result = client.fetch_raw_diff(PR_ID)

    assert result == diff_text


@responses.activate
def test_fetch_raw_diff_raises_on_error_status(client):
    responses.get(f"{API_BASE}/diff", json={"error": {"message": "Forbidden"}}, status=403)

    with pytest.raises(BitbucketClientError, match="403"):
        client.fetch_raw_diff(PR_ID)


@responses.activate
def test_post_comment_sends_content_raw(client):
    captured = responses.post(f"{API_BASE}/comments", json={"id": 1}, status=201)

    result = client.post_comment(PR_ID, "Looks good.")

    assert result == {"id": 1}
    sent_body = json.loads(captured.calls[0].request.body)
    assert sent_body == {"content": {"raw": "Looks good."}}


@responses.activate
def test_post_comment_includes_inline_anchor_when_given(client):
    captured = responses.post(f"{API_BASE}/comments", json={"id": 2}, status=201)

    client.post_comment(PR_ID, "Fix this.", inline={"path": "foo.py", "to": 5})

    sent_body = json.loads(captured.calls[0].request.body)
    assert sent_body == {"content": {"raw": "Fix this."}, "inline": {"path": "foo.py", "to": 5}}


@responses.activate
def test_post_comment_raises_on_error_status(client):
    responses.post(f"{API_BASE}/comments", json={"error": {"message": "Unprocessable"}}, status=422)

    with pytest.raises(BitbucketClientError, match="422"):
        client.post_comment(PR_ID, "x")


def test_bitbucket_provider_satisfies_vcs_provider_protocol(client):
    provider = BitbucketProvider(client, PR_ID)

    assert isinstance(provider, VCSProvider)


@responses.activate
def test_bitbucket_provider_fetch_pr_files_matches_diffstat_to_patches(client):
    responses.get(
        f"{API_BASE}/diffstat",
        json={
            "values": [
                {"status": "modified", "old": {"path": "foo.py"}, "new": {"path": "foo.py"}}
            ]
        },
        status=200,
    )
    responses.get(
        f"{API_BASE}/diff",
        body=(
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,1 +1,1 @@\n-a\n+b\n"
        ),
        status=200,
    )
    provider = BitbucketProvider(client, PR_ID)

    files = provider.fetch_pr_files()

    assert len(files) == 1
    assert files[0].filename == "foo.py"
    assert files[0].patch.startswith("@@ -1,1 +1,1 @@")


@responses.activate
def test_bitbucket_provider_fetch_pr_files_falls_back_to_old_path_for_deleted_files(client):
    responses.get(
        f"{API_BASE}/diffstat",
        json={"values": [{"status": "removed", "old": {"path": "removed.py"}, "new": None}]},
        status=200,
    )
    responses.get(f"{API_BASE}/diff", body="", status=200)
    provider = BitbucketProvider(client, PR_ID)

    files = provider.fetch_pr_files()

    assert files[0].filename == "removed.py"


@responses.activate
def test_bitbucket_provider_fetch_pr_files_handles_renamed_file(client):
    responses.get(
        f"{API_BASE}/diffstat",
        json={
            "values": [
                {
                    "status": "renamed",
                    "old": {"path": "old_name.py"},
                    "new": {"path": "new_name.py"},
                }
            ]
        },
        status=200,
    )
    responses.get(
        f"{API_BASE}/diff",
        body=(
            "diff --git a/old_name.py b/new_name.py\n"
            "--- a/old_name.py\n"
            "+++ b/new_name.py\n"
            "@@ -1,1 +1,1 @@\n-x\n+y\n"
        ),
        status=200,
    )
    provider = BitbucketProvider(client, PR_ID)

    files = provider.fetch_pr_files()

    assert files[0].filename == "new_name.py"
    assert "+y" in files[0].patch


@responses.activate
def test_bitbucket_provider_fetch_pr_files_warns_on_diffstat_diff_mismatch(client, capsys):
    responses.get(
        f"{API_BASE}/diffstat",
        json={
            "values": [
                {"status": "modified", "old": {"path": "foo.py"}, "new": {"path": "foo.py"}}
            ]
        },
        status=200,
    )
    responses.get(f"{API_BASE}/diff", body="", status=200)
    provider = BitbucketProvider(client, PR_ID)

    files = provider.fetch_pr_files()

    assert files[0].patch is None
    assert "::warning::" in capsys.readouterr().err


@responses.activate
def test_fetch_diffstat_rejects_next_url_outside_api_base(client):
    responses.get(
        f"{API_BASE}/diffstat",
        json={"values": [], "next": "https://evil.example.com/steal-token"},
        status=200,
    )

    with pytest.raises(BitbucketClientError, match="evil.example.com"):
        client.fetch_diffstat(PR_ID)


@responses.activate
def test_bitbucket_provider_fetch_pr_files_raises_when_both_paths_missing(client):
    responses.get(
        f"{API_BASE}/diffstat",
        json={"values": [{"status": "modified", "old": None, "new": None}]},
        status=200,
    )
    responses.get(f"{API_BASE}/diff", body="", status=200)
    provider = BitbucketProvider(client, PR_ID)

    with pytest.raises(BitbucketClientError, match="path"):
        provider.fetch_pr_files()


@responses.activate
def test_bitbucket_provider_post_review_posts_summary_and_inline_comments(client):
    captured_summary = responses.post(f"{API_BASE}/comments", json={"id": 1}, status=201)
    provider = BitbucketProvider(client, PR_ID)
    comments = [NormalizedComment(path="foo.py", line=5, body="fix this")]

    result = provider.post_review("Summary text", comments)

    assert result == {"summary": {"id": 1}, "comments": [{"id": 1}]}
    first_call_body = json.loads(captured_summary.calls[0].request.body)
    assert first_call_body == {"content": {"raw": "Summary text"}}
    second_call_body = json.loads(captured_summary.calls[1].request.body)
    assert second_call_body == {
        "content": {"raw": "fix this"},
        "inline": {"path": "foo.py", "to": 5},
    }
