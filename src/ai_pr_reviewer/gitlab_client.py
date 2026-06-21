"""Minimal GitLab REST API client for fetching MR diffs and posting reviews.

GitLab has no single "submit a review" endpoint like GitHub: a summary is posted as a regular MR
note, and each inline comment is posted as its own discussion thread, addressed via a `position`
object that pins the three commit SHAs (base/start/head) the diff was computed against — fetched
once per review from the MR detail endpoint, not derived from anything attacker-controlled.
"""

from urllib.parse import quote

import requests

from ai_pr_reviewer.vcs_provider import ChangedFile, NormalizedComment

PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 30


class GitLabClientError(Exception):
    """Raised when the GitLab API returns an error response."""


class GitLabClient:
    def __init__(self, token: str, project_id: str, base_url: str = "https://gitlab.com"):
        self._project_id_encoded = quote(str(project_id), safe="")
        self._api_base = f"{base_url.rstrip('/')}/api/v4"
        self._session = requests.Session()
        self._session.headers.update({"PRIVATE-TOKEN": token})

    def _project_url(self, path: str) -> str:
        return f"{self._api_base}/projects/{self._project_id_encoded}{path}"

    def _raise_for_status(self, response: requests.Response) -> None:
        if not response.ok:
            raise GitLabClientError(
                f"GitLab API request to {response.url} failed with {response.status_code}: "
                f"{response.text[:500]}"
            )

    def fetch_mr_diffs(self, mr_iid: int) -> list[dict]:
        diffs: list[dict] = []
        page = 1
        while True:
            response = self._session.get(
                self._project_url(f"/merge_requests/{mr_iid}/diffs"),
                params={"per_page": PER_PAGE, "page": page},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            self._raise_for_status(response)
            batch = response.json()
            diffs.extend(batch)
            if len(batch) < PER_PAGE:
                break
            page += 1
        return diffs

    def fetch_diff_refs(self, mr_iid: int) -> dict:
        response = self._session.get(
            self._project_url(f"/merge_requests/{mr_iid}"),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._raise_for_status(response)
        diff_refs = response.json().get("diff_refs")
        if not isinstance(diff_refs, dict):
            raise GitLabClientError("GitLab merge request response missing 'diff_refs'")
        return diff_refs

    def post_note(self, mr_iid: int, body: str) -> dict:
        response = self._session.post(
            self._project_url(f"/merge_requests/{mr_iid}/notes"),
            json={"body": body},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._raise_for_status(response)
        return response.json()

    def post_discussion(self, mr_iid: int, body: str, position: dict) -> dict:
        response = self._session.post(
            self._project_url(f"/merge_requests/{mr_iid}/discussions"),
            json={"body": body, "position": position},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._raise_for_status(response)
        return response.json()


class GitLabProvider:
    """Adapts GitLabClient to the provider-agnostic VCSProvider interface."""

    def __init__(self, client: GitLabClient, mr_iid: int):
        self._client = client
        self._mr_iid = mr_iid

    def fetch_pr_files(self) -> list[ChangedFile]:
        raw_diffs = self._client.fetch_mr_diffs(self._mr_iid)
        files = []
        for d in raw_diffs:
            filename = d.get("new_path") or d.get("old_path")
            if not filename:
                raise GitLabClientError(
                    f"GitLab diff entry has neither 'new_path' nor 'old_path': {d!r}"[:500]
                )
            files.append(ChangedFile(filename=filename, patch=d.get("diff") or None))
        return files

    def post_review(self, summary: str, comments: list[NormalizedComment]) -> dict:
        note_result = self._client.post_note(self._mr_iid, summary)

        discussion_results = []
        if comments:
            diff_refs = self._client.fetch_diff_refs(self._mr_iid)
            for comment in comments:
                position = {
                    "position_type": "text",
                    "base_sha": diff_refs["base_sha"],
                    "start_sha": diff_refs["start_sha"],
                    "head_sha": diff_refs["head_sha"],
                    "old_path": comment.path,
                    "new_path": comment.path,
                    "new_line": comment.line,
                }
                if comment.old_line is not None:
                    position["old_line"] = comment.old_line
                discussion_results.append(
                    self._client.post_discussion(self._mr_iid, comment.body, position)
                )

        return {"note": note_result, "discussions": discussion_results}
