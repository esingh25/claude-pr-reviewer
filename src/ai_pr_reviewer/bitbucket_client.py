"""Minimal Bitbucket Cloud REST API client for fetching PR diffs and posting reviews.

Bitbucket has no single "submit a review" endpoint either: a summary is posted as a top-level PR
comment, and each inline comment is posted as its own comment with an `inline` anchor (`to` for a
line in the destination/new file — the only case this project ever comments on). Unlike GitHub or
GitLab, comment text is nested under `content.raw` rather than a flat `body` field.

Bitbucket's API also doesn't expose per-file diffs directly: `/diffstat` lists the changed files
but not their patch text, and `/diff` returns one combined unified diff for the whole PR — so
`BitbucketProvider.fetch_pr_files` fetches both and splits the combined diff via
`diff_parser.split_unified_diff_by_file` to recover per-file patches.

This targets Bitbucket Cloud only, not the separately-architected Bitbucket Server/Data Center
product.
"""

import sys

import requests

from ai_pr_reviewer.diff_parser import split_unified_diff_by_file
from ai_pr_reviewer.vcs_provider import ChangedFile, NormalizedComment

API_BASE = "https://api.bitbucket.org/2.0"
PAGE_LEN = 100
REQUEST_TIMEOUT_SECONDS = 30


class BitbucketClientError(Exception):
    """Raised when the Bitbucket API returns an error response."""


class BitbucketClient:
    def __init__(self, token: str, workspace: str, repo_slug: str):
        self._workspace = workspace
        self._repo_slug = repo_slug
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def _pr_url(self, pr_id: int, path: str) -> str:
        return (
            f"{API_BASE}/repositories/{self._workspace}/{self._repo_slug}"
            f"/pullrequests/{pr_id}{path}"
        )

    def _raise_for_status(self, response: requests.Response) -> None:
        if not response.ok:
            raise BitbucketClientError(
                f"Bitbucket API request to {response.url} failed with {response.status_code}: "
                f"{response.text[:500]}"
            )

    def fetch_diffstat(self, pr_id: int) -> list[dict]:
        entries: list[dict] = []
        url: str | None = self._pr_url(pr_id, "/diffstat")
        params: dict | None = {"pagelen": PAGE_LEN}
        while url:
            # Bitbucket's own "next" page link, not attacker input — but never follow it
            # off-host, since every request here carries the bearer token.
            if not url.startswith(API_BASE):
                raise BitbucketClientError(
                    f"Refusing to follow pagination URL outside {API_BASE}: {url!r}"
                )
            response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            self._raise_for_status(response)
            data = response.json()
            entries.extend(data.get("values", []))
            url = data.get("next")
            params = None
        return entries

    def fetch_raw_diff(self, pr_id: int) -> str:
        response = self._session.get(
            self._pr_url(pr_id, "/diff"), timeout=REQUEST_TIMEOUT_SECONDS
        )
        self._raise_for_status(response)
        return response.text

    def post_comment(self, pr_id: int, body: str, inline: dict | None = None) -> dict:
        payload: dict = {"content": {"raw": body}}
        if inline:
            payload["inline"] = inline
        response = self._session.post(
            self._pr_url(pr_id, "/comments"), json=payload, timeout=REQUEST_TIMEOUT_SECONDS
        )
        self._raise_for_status(response)
        return response.json()


class BitbucketProvider:
    """Adapts BitbucketClient to the provider-agnostic VCSProvider interface."""

    def __init__(self, client: BitbucketClient, pr_id: int):
        self._client = client
        self._pr_id = pr_id

    def fetch_pr_files(self) -> list[ChangedFile]:
        diffstat_entries = self._client.fetch_diffstat(self._pr_id)
        per_file_patches = split_unified_diff_by_file(self._client.fetch_raw_diff(self._pr_id))

        files = []
        for entry in diffstat_entries:
            new_file = entry.get("new") or {}
            old_file = entry.get("old") or {}
            filename = new_file.get("path") or old_file.get("path")
            if not filename:
                raise BitbucketClientError(
                    f"Bitbucket diffstat entry has neither new.path nor old.path: {entry!r}"[:500]
                )
            if filename not in per_file_patches:
                print(
                    f"::warning::Bitbucket diffstat reports '{filename}' changed but no "
                    "matching patch was found in the combined diff; skipping.",
                    file=sys.stderr,
                )
            files.append(ChangedFile(filename=filename, patch=per_file_patches.get(filename)))
        return files

    def post_review(self, summary: str, comments: list[NormalizedComment]) -> dict:
        summary_result = self._client.post_comment(self._pr_id, summary)
        comment_results = [
            self._client.post_comment(
                self._pr_id, comment.body, inline={"path": comment.path, "to": comment.line}
            )
            for comment in comments
        ]
        return {"summary": summary_result, "comments": comment_results}
