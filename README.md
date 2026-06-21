# Claude PR Reviewer

AI-powered pull/merge request reviewer using the [Claude API](https://docs.anthropic.com/). Ships
as a GitHub Action and, as of this version, also as a pip-installable CLI for GitLab CI (note:
the CLI is built and tested locally but **not yet published to PyPI** — see "GitLab CI" below).

## How it works

On a pull/merge request event, the tool:
1. Fetches the PR/MR's changed files and unified diffs via the GitHub or GitLab REST API.
2. For each file, scans its diff for import/include statements and, if any match another file
   already in the same PR's changed-file list, reads a capped excerpt of that related file from
   the local checkout to give Claude cross-file context (see "Cross-file context" below).
3. Sends each file's diff — plus any related-file excerpts — to Claude with a review prompt,
   asking for structured JSON feedback.
4. Filters suggestions to lines that are actually part of the diff.
5. Posts a single review with inline comments and a summary (a GitHub PR review, or a GitLab MR
   note + discussion threads).

### Cross-file context

Beyond a file's own diff, the action looks for import/include statements (Python, JS/TS, Java,
C/C++) and matches them against other files already changed in the *same* PR — never an arbitrary
repo-wide file index, so the only files ever read are ones the PR author already controls and can
already see in their own diff. Matches are capped at 3 related files and 2000 characters each.

This sends more file content to Claude (a third party) than diffs alone — up to 6000 extra
characters of related-file content per review, beyond what each file's own diff hunks expose. For
privacy-sensitive private repos, set `enable-cross-file-context: 'false'` to disable this and only
ever send diff hunks.

## Metrics

Each run emits a structured metrics record (repo, PR number, head SHA, model, files reviewed,
comments posted, severity breakdown, duration, status) two ways:
- As a readable markdown block in the job's **step summary** (visible in the Actions UI run page).
- As an action **output** (`metrics`, a compact JSON string) you can chain in your own workflow.

This is intentionally GitHub-native only — the action never commits anything back to your repo or
requests `contents: write`. If you want to track metrics over time, persist the output yourself,
e.g.:

```yaml
      - uses: esingh25/claude-pr-reviewer@v1
        id: claude_review
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Append metrics and commit
        run: echo '${{ steps.claude_review.outputs.metrics }}' >> .claude-pr-reviewer/metrics.jsonl
      - uses: EndBug/add-and-commit@v9
        with:
          add: .claude-pr-reviewer/metrics.jsonl
          message: 'chore: record review metrics'
```

(Use a separate branch for this if you don't want metrics commits mixed into PR history.)

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
| `enable-cross-file-context` | no | `true` | Include related-file excerpts as extra context (see above) |

## GitLab CI

The same tool is installable as a CLI and runs the same review logic against GitLab merge
requests. It is **not published to PyPI** — install it from this repo directly:

```yaml
# .gitlab-ci.yml
claude_review:
  image: python:3.11
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - pip install "git+https://github.com/esingh25/claude-pr-reviewer.git"
    - ai-pr-reviewer
  variables:
    GITLAB_TOKEN: $GITLAB_TOKEN          # a project/personal access token with API scope
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

Configuration is read from GitLab's own predefined CI/CD variables (`CI_PROJECT_PATH`,
`CI_MERGE_REQUEST_IID`, `CI_COMMIT_SHA`, `CI_SERVER_URL` for self-hosted instances) plus
`GITLAB_TOKEN`/`ANTHROPIC_API_KEY`, which you set as masked CI/CD variables in the project's
Settings → CI/CD → Variables. `INPUT_MODEL`/`INPUT_MAX_DIFF_CHARS`/`INPUT_MAX_FILES`/
`INPUT_ENABLE_CROSS_FILE_CONTEXT` work the same as the GitHub Action inputs above.

GitLab's discussion API needs `old_line`/`new_line` set differently depending on whether a
comment lands on an added or an unchanged context line; this is handled correctly for both cases
via `diff_parser.FileDiff.old_lineno_for()`.

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
  config.py          # env parsing - GitHub Actions or GitLab CI, dispatched by provider
  diff_parser.py      # unified diff -> line-numbered FileDiff
  context_finder.py   # finds related files in the same PR for cross-file context
  vcs_provider.py      # provider-agnostic types (ChangedFile, NormalizedComment, VCSProvider)
  github_client.py    # GitHub REST API + GitHubProvider adapter
  gitlab_client.py     # GitLab REST API + GitLabProvider adapter
  claude_client.py    # Claude API call + structured response parsing
  review_engine.py    # orchestrates the end-to-end review against any VCSProvider
  metrics.py           # builds + emits per-run metrics (step output/summary, no git commits)
  __main__.py          # entrypoint - GitHub Action and the `ai-pr-reviewer` CLI both call this
```

## License

[MIT](LICENSE)
