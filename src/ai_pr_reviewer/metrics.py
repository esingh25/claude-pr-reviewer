"""Build and emit per-run quality metrics via GitHub-native outputs.

Deliberately does not commit anything back to the repository: writes only to the
GITHUB_OUTPUT/GITHUB_STEP_SUMMARY files the Actions runner already provides, so no extra
permissions (contents: write) or custom git automation are needed. Teams that want to persist
metrics over time can chain their own step using an established action (see README).

Every field rendered into the step summary comes from `Config`/`ReviewResult` — repo/owner from
GITHUB_REPOSITORY, the SHA from the trusted event payload, severities from a fixed allowlist
enforced in claude_client.py — never from the untrusted PR diff or Claude's free-text comment
output, so no markdown-escaping is needed here (unlike the @mention/#ref sanitization applied to
posted review comments, which do carry untrusted text).
"""

import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import requests

from ai_pr_reviewer.config import Config
from ai_pr_reviewer.review_engine import ReviewResult


@dataclass(frozen=True)
class MetricsRecord:
    repo: str
    pr_number: int
    head_sha: str
    provider: str
    timestamp: str
    model: str
    files_reviewed: int
    comments_posted: int
    severity_counts: dict[str, int]
    duration_seconds: float
    status: str = "success"


def build_metrics_record(
    config: Config,
    result: ReviewResult,
    duration_seconds: float,
    now: datetime | None = None,
    status: str = "success",
) -> MetricsRecord:
    timestamp = (now or datetime.now(UTC)).isoformat()
    return MetricsRecord(
        repo=f"{config.repo_owner}/{config.repo_name}",
        pr_number=config.pr_number,
        head_sha=config.head_sha,
        provider=config.provider,
        timestamp=timestamp,
        model=config.model,
        files_reviewed=result.files_reviewed,
        comments_posted=result.comments_posted,
        severity_counts=dict(result.severity_counts),
        duration_seconds=round(duration_seconds, 3),
        status=status,
    )


def render_step_summary(record: MetricsRecord) -> str:
    severity_line = ", ".join(f"{name}: {count}" for name, count in record.severity_counts.items())
    return (
        "## Claude PR Review Metrics\n\n"
        f"- **Status:** {record.status}\n"
        f"- **Repo:** {record.repo}\n"
        f"- **PR:** #{record.pr_number} ({record.head_sha[:7]})\n"
        f"- **Model:** {record.model}\n"
        f"- **Files reviewed:** {record.files_reviewed}\n"
        f"- **Comments posted:** {record.comments_posted}\n"
        f"- **Severity breakdown:** {severity_line}\n"
        f"- **Duration:** {record.duration_seconds}s\n"
    )


def write_github_output(record: MetricsRecord, output_path: str | None) -> None:
    if not output_path:
        return
    try:
        compact_json = json.dumps(asdict(record), separators=(",", ":"))
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(f"metrics={compact_json}\n")
    except OSError as exc:
        print(f"::warning::Failed to write metrics output: {exc}", file=sys.stderr)


def write_step_summary(text: str, summary_path: str | None) -> None:
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        print(f"::warning::Failed to write step summary: {exc}", file=sys.stderr)


def post_to_dashboard(
    record: MetricsRecord, dashboard_url: str | None, api_key: str | None
) -> None:
    """Optionally POST this run's metrics to a self-hosted dashboard. Opt-in only: a no-op
    unless both DASHBOARD_URL and DASHBOARD_API_KEY are configured. Never raises — a dashboard
    outage must never fail the review run itself."""
    if not dashboard_url or not api_key:
        return
    try:
        response = requests.post(
            f"{dashboard_url.rstrip('/')}/api/metrics",
            json=asdict(record),
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"::warning::Failed to post metrics to dashboard: {exc}", file=sys.stderr)
