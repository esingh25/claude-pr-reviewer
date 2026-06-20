"""Load review configuration from environment variables and the GitHub event payload."""

import json
import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_DIFF_CHARS = 12000
DEFAULT_MAX_FILES = 50


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    github_token: str = field(repr=False)
    anthropic_api_key: str = field(repr=False)
    repo_owner: str
    repo_name: str
    pr_number: int
    base_sha: str
    head_sha: str
    model: str
    max_diff_chars: int
    max_files: int


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

    fields_valid = (
        isinstance(number, int) and isinstance(base_sha, str) and isinstance(head_sha, str)
    )
    if not fields_valid:
        raise ConfigError(
            "Event payload's pull_request is missing required fields: "
            "number (int), base.sha (str), head.sha (str)"
        )
    return number, base_sha, head_sha


def load_config() -> Config:
    github_token = _require_env("GITHUB_TOKEN")
    anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
    repository = _require_env("GITHUB_REPOSITORY")
    event_path = _require_env("GITHUB_EVENT_PATH")

    repo_owner, _, repo_name = repository.partition("/")

    pull_request = _load_pull_request_event(event_path)
    pr_number, base_sha, head_sha = _extract_pr_fields(pull_request)

    return Config(
        github_token=github_token,
        anthropic_api_key=anthropic_api_key,
        repo_owner=repo_owner,
        repo_name=repo_name,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
        model=os.environ.get("INPUT_MODEL") or DEFAULT_MODEL,
        max_diff_chars=_parse_int_env("INPUT_MAX_DIFF_CHARS", DEFAULT_MAX_DIFF_CHARS),
        max_files=_parse_int_env("INPUT_MAX_FILES", DEFAULT_MAX_FILES),
    )
