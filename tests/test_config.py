import json

import pytest

from ai_pr_reviewer.config import ConfigError, load_config

EVENT_PAYLOAD = {
    "pull_request": {
        "number": 42,
        "base": {"sha": "abc123"},
        "head": {"sha": "def456"},
    }
}


@pytest.fixture
def event_file(tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(EVENT_PAYLOAD))
    return path


@pytest.fixture
def base_env(monkeypatch, event_file):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key-123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "esingh25/claude-pr-reviewer")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    monkeypatch.delenv("INPUT_MODEL", raising=False)
    monkeypatch.delenv("INPUT_MAX_DIFF_CHARS", raising=False)


def test_load_config_parses_required_fields(base_env):
    config = load_config()

    assert config.github_token == "gh-token-123"
    assert config.anthropic_api_key == "anthropic-key-123"
    assert config.repo_owner == "esingh25"
    assert config.repo_name == "claude-pr-reviewer"
    assert config.pr_number == 42
    assert config.base_sha == "abc123"
    assert config.head_sha == "def456"


def test_load_config_applies_defaults(base_env):
    config = load_config()

    assert config.model == "claude-sonnet-4-6"
    assert config.max_diff_chars == 12000
    assert config.max_files == 50


def test_load_config_honors_input_overrides(base_env, monkeypatch):
    monkeypatch.setenv("INPUT_MODEL", "claude-opus-4-8")
    monkeypatch.setenv("INPUT_MAX_DIFF_CHARS", "5000")
    monkeypatch.setenv("INPUT_MAX_FILES", "10")

    config = load_config()

    assert config.model == "claude-opus-4-8"
    assert config.max_diff_chars == 5000
    assert config.max_files == 10


def test_load_config_raises_when_max_diff_chars_not_integer(base_env, monkeypatch):
    monkeypatch.setenv("INPUT_MAX_DIFF_CHARS", "not-a-number")

    with pytest.raises(ConfigError, match="INPUT_MAX_DIFF_CHARS"):
        load_config()


def test_load_config_raises_when_max_files_not_integer(base_env, monkeypatch):
    monkeypatch.setenv("INPUT_MAX_FILES", "not-a-number")

    with pytest.raises(ConfigError, match="INPUT_MAX_FILES"):
        load_config()


def test_config_repr_does_not_leak_secrets(base_env):
    config = load_config()

    rendered = repr(config)

    assert "gh-token-123" not in rendered
    assert "anthropic-key-123" not in rendered


def test_load_config_raises_when_github_token_missing(base_env, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        load_config()


def test_load_config_raises_when_anthropic_key_missing(base_env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_config()


def test_load_config_raises_when_repository_env_missing(base_env, monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    with pytest.raises(ConfigError, match="GITHUB_REPOSITORY"):
        load_config()


def test_load_config_raises_when_event_path_missing(base_env, monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    with pytest.raises(ConfigError, match="GITHUB_EVENT_PATH"):
        load_config()


def test_load_config_raises_when_event_file_not_pull_request(base_env, monkeypatch, tmp_path):
    push_event_path = tmp_path / "push_event.json"
    push_event_path.write_text(json.dumps({"ref": "refs/heads/main"}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(push_event_path))

    with pytest.raises(ConfigError, match="pull_request"):
        load_config()


@pytest.mark.parametrize(
    "malformed_pull_request",
    [
        {"base": {"sha": "abc123"}, "head": {"sha": "def456"}},  # missing number
        {"number": "not-an-int", "base": {"sha": "abc123"}, "head": {"sha": "def456"}},
        {"number": 42, "base": {}, "head": {"sha": "def456"}},  # missing base.sha
        {"number": 42, "base": {"sha": "abc123"}, "head": None},  # head not an object
    ],
)
def test_load_config_raises_when_pull_request_fields_malformed(
    base_env, monkeypatch, tmp_path, malformed_pull_request
):
    event_path = tmp_path / "malformed_event.json"
    event_path.write_text(json.dumps({"pull_request": malformed_pull_request}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    with pytest.raises(ConfigError, match="number|base.sha|head.sha"):
        load_config()
