"""Load review configuration from environment variables — GitHub Actions, GitLab CI, or
Bitbucket Pipelines."""

import json
import os
import re
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_DIFF_CHARS = 12000
DEFAULT_MAX_FILES = 50
DEFAULT_GITLAB_BASE_URL = "https://gitlab.com"
_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _is_valid_sha(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value))


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    provider: str
    vcs_token: str = field(repr=False)
    anthropic_api_key: str = field(repr=False)
    repo_owner: str
    repo_name: str
    pr_number: int
    base_sha: str
    head_sha: str
    model: str
    max_diff_chars: int
    max_files: int
    workspace_root: str
    enable_cross_file_context: bool
    gitlab_base_url: str


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Required environment variable {name} is not set")
    return value


def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _parse_required_int_env(name: str) -> int:
    raw = _require_env(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if not raw:
        return default
    return raw.strip().lower() not in ("false", "0", "no")


def _load_pull_request_event(event_path: str) -> dict:
    with open(event_path, encoding="utf-8") as f:
        event = json.load(f)

    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        raise ConfigError("Event payload does not contain a 'pull_request' object (wrong trigger?)")
    return pull_request


def _extract_pr_fields(pull_request: dict) -> tuple[int, str, str]:
    number = pull_request.get("number")
    base = pull_request.get("base")
    head = pull_request.get("head")
    base_sha = base.get("sha") if isinstance(base, dict) else None
    head_sha = head.get("sha") if isinstance(head, dict) else None

    fields_valid = isinstance(number, int) and _is_valid_sha(base_sha) and _is_valid_sha(head_sha)
    if not fields_valid:
        raise ConfigError(
            "Event payload's pull_request is missing required fields: "
            "number (int), base.sha (40-char hex str), head.sha (40-char hex str)"
        )
    return number, base_sha, head_sha


def _common_fields() -> dict:
    return {
        "anthropic_api_key": _require_env("ANTHROPIC_API_KEY"),
        "model": os.environ.get("INPUT_MODEL") or DEFAULT_MODEL,
        "max_diff_chars": _parse_int_env("INPUT_MAX_DIFF_CHARS", DEFAULT_MAX_DIFF_CHARS),
        "max_files": _parse_int_env("INPUT_MAX_FILES", DEFAULT_MAX_FILES),
        "enable_cross_file_context": _parse_bool_env("INPUT_ENABLE_CROSS_FILE_CONTEXT", True),
    }


def _load_github_config() -> Config:
    github_token = _require_env("GITHUB_TOKEN")
    repository = _require_env("GITHUB_REPOSITORY")
    event_path = _require_env("GITHUB_EVENT_PATH")

    repo_owner, _, repo_name = repository.partition("/")

    pull_request = _load_pull_request_event(event_path)
    pr_number, base_sha, head_sha = _extract_pr_fields(pull_request)

    return Config(
        provider="github",
        vcs_token=github_token,
        repo_owner=repo_owner,
        repo_name=repo_name,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
        workspace_root=os.environ.get("GITHUB_WORKSPACE") or ".",
        gitlab_base_url=DEFAULT_GITLAB_BASE_URL,
        **_common_fields(),
    )


def _load_gitlab_config() -> Config:
    gitlab_token = _require_env("GITLAB_TOKEN")
    project_path = _require_env("CI_PROJECT_PATH")
    mr_iid = _parse_required_int_env("CI_MERGE_REQUEST_IID")
    head_sha = _require_env("CI_COMMIT_SHA")

    repo_owner, _, repo_name = project_path.rpartition("/")
    if not repo_owner or not repo_name:
        raise ConfigError(
            f"CI_PROJECT_PATH must be in 'namespace/project' form, got {project_path!r}"
        )

    # CI_SERVER_URL is set by the GitLab runner itself (the instance's own configured URL),
    # never by anything in the MR diff/title/description — same trust tier as GITLAB_TOKEN.
    gitlab_base_url = os.environ.get("CI_SERVER_URL") or DEFAULT_GITLAB_BASE_URL
    if not gitlab_base_url.startswith(("http://", "https://")):
        raise ConfigError(f"CI_SERVER_URL must be an http(s) URL, got {gitlab_base_url!r}")

    return Config(
        provider="gitlab",
        vcs_token=gitlab_token,
        repo_owner=repo_owner,
        repo_name=repo_name,
        pr_number=mr_iid,
        # CI_MERGE_REQUEST_DIFF_BASE_SHA is only set on MR-triggered pipelines and isn't used by
        # GitLabProvider's own API calls (which fetch fresh diff_refs) — best-effort, for metrics
        # display only, so it's intentionally not validated as strict 40-char hex like GitHub's.
        base_sha=os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA") or "",
        head_sha=head_sha,
        workspace_root=os.environ.get("CI_PROJECT_DIR") or ".",
        gitlab_base_url=gitlab_base_url,
        **_common_fields(),
    )


def _load_bitbucket_config() -> Config:
    bitbucket_token = _require_env("BITBUCKET_TOKEN")
    workspace = _require_env("BITBUCKET_WORKSPACE")
    repo_slug = _require_env("BITBUCKET_REPO_SLUG")
    pr_id = _parse_required_int_env("BITBUCKET_PR_ID")
    head_sha = _require_env("BITBUCKET_COMMIT")

    return Config(
        provider="bitbucket",
        vcs_token=bitbucket_token,
        repo_owner=workspace,
        repo_name=repo_slug,
        pr_number=pr_id,
        # Bitbucket Pipelines has no predefined "base sha" variable; best-effort/unused, like
        # GitLab's equivalent field — Bitbucket's own diff endpoints don't need it either.
        base_sha="",
        head_sha=head_sha,
        workspace_root=os.environ.get("BITBUCKET_CLONE_DIR") or ".",
        gitlab_base_url=DEFAULT_GITLAB_BASE_URL,
        **_common_fields(),
    )


def load_config() -> Config:
    if _parse_bool_env("GITLAB_CI", False):
        return _load_gitlab_config()
    if os.environ.get("BITBUCKET_BUILD_NUMBER"):
        return _load_bitbucket_config()
    return _load_github_config()
