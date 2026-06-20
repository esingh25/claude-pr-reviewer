# Claude PR Reviewer

AI-powered GitHub Action that reviews pull request diffs using the [Claude API](https://docs.anthropic.com/) and posts inline review comments.

## How it works

On a pull request event, the action:
1. Fetches the PR's changed files and unified diffs via the GitHub REST API.
2. Sends each file's diff to Claude with a review prompt, asking for structured JSON feedback.
3. Filters suggestions to lines that are actually part of the diff.
4. Posts a single GitHub PR review with inline comments and a summary.

## Usage

Add a workflow to the repository you want reviewed:

```yaml
# .github/workflows/claude-review.yml
name: Claude PR Review

on:
  pull_request:  # do NOT use pull_request_target — see Security notes below
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: esingh25/claude-pr-reviewer@v1
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Add `ANTHROPIC_API_KEY` as a repository secret (Settings → Secrets and variables → Actions).

### Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `anthropic-api-key` | yes | — | Anthropic API key used to call Claude |
| `github-token` | no | `${{ github.token }}` | Token used to fetch diffs and post the review |
| `model` | no | `claude-sonnet-4-6` | Claude model to use |
| `max-diff-chars` | no | `12000` | Max diff characters sent to Claude per file |
| `max-files` | no | `50` | Max changed files reviewed per PR (bounds API cost) |

## Security notes

- **Never trigger this action with `pull_request_target`.** That event runs with the base
  repository's (privileged) token and permissions even when reviewing an untrusted fork's diff.
  Use `pull_request` (as shown above), which GitHub automatically restricts to a read-only
  token for fork-originated PRs.
- PR diff content is **untrusted input**. The system prompt instructs Claude to treat diff text
  purely as code to review and never as instructions, and review comments are capped in count
  and length — but treat anything the bot posts as AI-generated and unverified, not as a trusted
  human assertion (every posted review is prefixed with a disclaimer for this reason).
- Don't grant this action more than `contents: read` + `pull-requests: write`.

## Local development

```bash
python -m venv .venv
.venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"

ruff check src tests
pytest --cov=ai_pr_reviewer --cov-report=term-missing
```

## Project layout

```
src/ai_pr_reviewer/
  config.py          # env/event-payload parsing
  diff_parser.py      # unified diff -> line-numbered FileDiff
  github_client.py    # GitHub REST API: fetch PR files, post review
  claude_client.py    # Claude API call + structured response parsing
  review_engine.py    # orchestrates the end-to-end review
  __main__.py          # action entrypoint
```

## License

[MIT](LICENSE)
