# Project Vision & Roadmap

## Vision

Claude PR Reviewer should grow into an AI code review assistant that goes beyond linting: it
should understand the *context* a change sits in (not just the diff in isolation), suggest
architectural improvements, flag security issues, work across whichever version-control platform
a team actually uses (not just GitHub), and give engineering teams a way to see how code quality
trends over time — all while staying genuinely helpful rather than generic.

The core technical challenges that follow from that: handling large codebases without blowing up
cost/latency, understanding context that spans multiple files, and producing suggestions specific
enough to a given team's standards to actually be worth reading.

## Current state — Phases 1, 2, 3a & 4 (shipped)

Live today at `esingh25/claude-pr-reviewer`:
- Composite GitHub Action, Python 3.11, triggered on `pull_request` events — and, as of Phase 4,
  also a pip-installable CLI (`ai-pr-reviewer`, not yet published to PyPI) runnable from GitLab CI
  or Bitbucket Pipelines.
- Calls the base Claude API (`claude-sonnet-4-6` by default) per changed file — no fine-tuning
  (confirmed unavailable for Claude via self-serve API, see Phase 5 below).
- **Cross-file context (Phase 2):** scans each file's diff for import/include statements
  (Python/JS/TS/Java/C/C++) and, on a match against another file already in the same PR, reads a
  capped excerpt of that file from the local checkout to give Claude extra context — opt-out via
  `enable-cross-file-context: 'false'` for privacy-sensitive repos.
- **Metrics MVP (Phase 3a):** emits a structured per-run metrics record (files reviewed, comments
  posted, severity breakdown, duration, status) as a step output and job step summary — no git
  commits, no new permissions. See "Metrics" in `README.md` for the optional self-persistence
  pattern.
- **Multi-VCS support (Phase 4):** `review_engine.py` depends only on a provider-agnostic
  `VCSProvider` interface (`vcs_provider.py`); `GitHubProvider` adapts the original GitHub client,
  `GitLabProvider`/`gitlab_client.py` add GitLab merge request support (summary as an MR note,
  inline comments as discussion threads with GitLab's SHA-based `position` contract, correctly
  handling both added-line and context-line comments), and `BitbucketProvider`/`bitbucket_client.py`
  add Bitbucket Cloud pull request support (summary + inline comments via `content.raw`, per-file
  patches reconstructed from Bitbucket's combined-diff endpoint via
  `diff_parser.split_unified_diff_by_file()`). See "GitLab CI" / "Bitbucket Pipelines" in
  `README.md`.
- Hardened for production use: prompt-injection-resistant system prompt (covers both diff and
  related-file content), `@mention`/`#ref` sanitization on posted comments, capped file/comment
  counts, strict validation of Claude's JSON response shape, symlink-aware path-traversal guard on
  related-file reads, SHA-hex format validation on event-payload fields, GitLab `CI_SERVER_URL`
  scheme validation, Bitbucket pagination host-allowlist, unambiguous filename derivation for
  Bitbucket's combined diffs (from `---`/`+++` lines, not the ambiguous `diff --git` header), 165
  tests / 99% coverage, clean lint, CI green. See `README.md` for usage and security notes.

These phases cover "flagging issues," "understanding context across multiple files" within a
single PR, a first cut at "tracking code quality over time," and "work across whichever
version-control platform a team actually uses" (GitHub, GitLab, and Bitbucket Cloud).
Everything below is what's needed to reach the fuller vision.

## Roadmap

Phases are sequenced by engineering dependency and infrastructure cost, not by how they were
originally pitched.

### Phase 2 — Cross-file context-aware review ✅ shipped

Directly addresses "understanding context across multiple files" and "not generic suggestions."
Implemented as `context_finder.py`: scans a file's diff for import/include statements and matches
them (by basename) against other files already changed in the same PR, reading capped excerpts
from the local checkout. No new infrastructure — pure extension of the existing GitHub Action.

### Phase 3 — Quality metrics tracking

Two stages, because the second stage requires an infrastructure/budget decision that's the
project owner's to make, not something to assume:

- **3a (MVP, no new infra) ✅ shipped:** after each review run, the action builds a metrics
  record (repo, PR number, head SHA, timestamp, model, files reviewed, comments posted, severity
  breakdown, duration, status) and emits it via two GitHub-native mechanisms only — a step
  `output` (JSON, for chaining) and the job's step summary (markdown) — deliberately with no git
  commits and no new permissions. The original design called for the action to commit a metrics
  file back into the repo itself, but that would need `contents: write` and custom git automation;
  emitting via outputs keeps the permission footprint unchanged and lets teams that want real
  persistence chain their own step with an established action (documented in `README.md`).
- **3b (hosted dashboard, requires an infra decision):** graduate to a small persistent service —
  closest reference found is `middlewarehq/middleware` (Python/FastAPI + Postgres, 1.6k+ stars,
  open-source DORA-metrics platform) — once cross-repo/cross-team aggregation is actually needed.
  This requires choosing and paying for hosting and should be a deliberate, separate decision, not
  something bundled into a "build everything" pass.

Sequenced after Phase 2 because metrics are only worth collecting once review quality itself has
improved past the single-file baseline.

### Phase 4 — Multi-VCS support ✅ shipped (GitHub, GitLab, Bitbucket Cloud)

Abstracted `github_client.py` behind a small provider interface (`vcs_provider.py`) so the same
review engine can run against GitLab merge requests and Bitbucket Cloud pull requests too, not
just GitHub PRs (Bitbucket Server/Data Center — a separately-architected product — is explicitly
out of scope). Confirmed via research that no lightweight, actively-maintained Python library
already does this — provider clients exist per-platform (PyGithub, python-gitlab,
atlassian-python-api) but nothing unifies diff-fetching and inline-comment-posting across all
three, so the hand-rolled interface was the right call rather than adding a heavy dependency.

Also repackaged the tool as a pip-installable CLI (`ai-pr-reviewer`, `[project.scripts]` entry in
`pyproject.toml`) so it can run from GitLab CI or Bitbucket Pipelines via `pip install` rather
than needing a GitHub-Action-shaped manifest — verified locally end-to-end for both (real, if
401-rejected-on-a-fake-token, requests reached each platform's actual API). Deliberately **not
published to PyPI** this session — that's a separate, explicit decision (package names are
effectively permanent once claimed).

Key design constraint: **GitLab is the hard case, design around it first.** GitHub's comment
addressing is stateless (`{path, line, side}`). GitLab requires a `position` object carrying three
SHAs (`base_sha`, `start_sha`, `head_sha`) plus separate `old_line`/`new_line` fields and a
`position_type` discriminator (`POST /projects/:id/merge_requests/:iid/discussions`). Bitbucket
sits in between — `path` + `to`/`from` line, but nests comment text under `content.raw` rather
than a flat `body` (`POST /repositories/{ws}/{repo}/pullrequests/{id}/comments`). If the provider
interface is designed GitHub-first, bolting GitLab on later forces a breaking change — so the
internal `ReviewComment`/provider-call shape needs to carry enough context (SHAs, old/new line,
a body-text field name mapping) to satisfy GitLab's stricter contract from day one, even though
GitHub/Bitbucket adapters will simply ignore the fields they don't need.

Diff retrieval per provider:
- GitHub: `GET /repos/{owner}/{repo}/pulls/{pr}/files`
- GitLab: `GET /projects/:id/merge_requests/:iid/diffs` (paginated; the older `/changes` endpoint
  is deprecated)
- Bitbucket: `GET /repositories/{ws}/{repo}/pullrequests/{id}/diffstat` (file list, no patch text)
  combined with `/diff` (one raw unified diff for the whole PR) — `diff_parser.
  split_unified_diff_by_file()` reconstructs per-file patches from the combined diff, matched
  against diffstat's `new.path`/`old.path` by filename.

### Phase 5 — Adapt review behavior to a team's historical feedback

The original pitch called this "fine-tuning language models on code review data." Research
confirmed Anthropic does **not** offer a self-serve fine-tuning API for Claude (unlike OpenAI) —
customization is consistently steered toward prompting, RAG, and prompt caching instead, with no
first-party fine-tuning endpoint accessible via a standard API key. **Reframing this phase
accordingly:**

- Retrieve the most relevant historical review comments (ideally ones a human marked as useful,
  via the Phase 3 resolution-status data) per diff, as few-shot context.
- Combine that retrieved set with a static style-guide block, placed behind a cached prompt
  prefix — Anthropic's prompt caching cuts repeated-context cost by roughly 90% on cache hits, so
  a rich, growing examples corpus stays cheap to include on every call.

This phase depends on Phase 3 existing first (it needs real accepted/dismissed comment data to
retrieve from), so it's sequenced last despite being the most "AI-flavored" item in the original
pitch.

## Open decisions before building Phase 3b or Phase 5

- Phase 3b requires choosing and budgeting for hosting (even a small VM/PaaS instance is an
  ongoing cost commitment) — explicit go-ahead needed before starting it.
- Publishing `ai-pr-reviewer` to PyPI (currently local-install-only) is a separate, explicit
  decision — package names are effectively permanent once claimed.
- Phase 5's RAG component needs a decision on retrieval mechanism (simple keyword/recency
  matching vs. an embedding-based vector search) once there's enough Phase 3 data to retrieve
  from.
