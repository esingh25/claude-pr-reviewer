"""Minimal GitHub REST API client for fetching PR diffs and posting reviews."""

from dataclasses import dataclass

import requests

from ai_pr_reviewer.vcs_provider import ChangedFile, NormalizedComment

API_BASE = "https://api.github.com"
PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 30


class GitHubClientError(Exception):
    """Raised when the GitHub API returns an error response."""


@dataclass(frozen=True)
class ReviewComment:
    path: str
    line: int
    side: str
    body: str


class GitHubClient:
    def __init__(self, token: str, owner: str, repo: str):
        self._owner = owner
        self._repo = repo
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _repo_url(self, path: str) -> str:
        return f"{API_BASE}/repos/{self._owner}/{self._repo}{path}"

    def _raise_for_status(self, response: requests.Response) -> None:
        if not response.ok:
            raise GitHubClientError(
                f"GitHub API request to {response.url} failed with {response.status_code}: "
                f"{response.text[:500]}"
            )

    def fetch_pr_files(self, pr_number: int) -> list[dict]:
        files: list[dict] = []
        page = 1
        while True:
            response = self._session.get(
                self._repo_url(f"/pulls/{pr_number}/files"),
                params={"per_page": PER_PAGE, "page": page},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            self._raise_for_status(response)
            batch = response.json()
            files.extend(batch)
            if len(batch) < PER_PAGE:
                break
            page += 1
        return files

    def post_review(
        self, pr_number: int, summary: str, comments: list[ReviewComment], event: str = "COMMENT"
    ) -> dict:
        payload = {
            "body": summary,
            "event": event,
            "comments": [
                {"path": c.path, "line": c.line, "side": c.side, "body": c.body} for c in comments
            ],
        }
        response = self._session.post(
            self._repo_url(f"/pulls/{pr_number}/reviews"),
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._raise_for_status(response)
        return response.json()


class GitHubProvider:
    """Adapts GitHubClient to the provider-agnostic VCSProvider interface."""

    def __init__(self, client: GitHubClient, pr_number: int):
        self._client = client
        self._pr_number = pr_number

    def fetch_pr_files(self) -> list[ChangedFile]:
        raw_files = self._client.fetch_pr_files(self._pr_number)
        return [ChangedFile(filename=f["filename"], patch=f.get("patch")) for f in raw_files]

    def post_review(self, summary: str, comments: list[NormalizedComment]) -> dict:
        github_comments = [
            ReviewComment(path=c.path, line=c.line, side="RIGHT", body=c.body) for c in comments
        ]
        return self._client.post_review(self._pr_number, summary=summary, comments=github_comments)
