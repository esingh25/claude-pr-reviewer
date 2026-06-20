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

## Current state — Phase 1 (shipped)

Live today at `esingh25/claude-pr-reviewer`:
- Composite GitHub Action, Python 3.11, triggered on `pull_request` events.
- Calls the base Claude API (`claude-sonnet-4-6` by default) per changed file — no fine-tuning,
  no cross-file context beyond the single file's diff.
- GitHub only (REST API for fetching diffs and posting inline review comments).
- No persistence — each run is stateless; nothing is tracked over time.
- Hardened for production use: prompt-injection-resistant system prompt, `@mention`/`#ref`
  sanitization on posted comments, capped file/comment counts, strict validation of Claude's
  JSON response shape, 99% test coverage, clean lint, CI green. See `README.md` for usage and
  security notes.

This phase already covers "flagging issues" and "understanding context" at the single-file level.
Everything below is what's needed to reach the fuller vision.

## Roadmap

Phases are sequenced by engineering dependency and infrastructure cost, not by how they were
originally pitched.

### Phase 2 — Cross-file context-aware review

Directly addresses "understanding context across multiple files" and "not generic suggestions."
Extend `review_engine.py`/`claude_client.py` so that, before prompting Claude on a file's diff, the
action also pulls in directly related files (e.g. files that import the changed file, or files it
imports) and includes relevant excerpts as extra context. No new infrastructure — pure extension
of the existing GitHub Action. Sequenced first because it's the highest-leverage quality
improvement available with zero new infra cost.

### Phase 3 — Quality metrics tracking

Two stages, because the second stage requires an infrastructure/budget decision that's the
project owner's to make, not something to assume:

- **3a (MVP, no new infra):** after each review run, append a record (repo, PR number, commit SHA,
  timestamp, files reviewed, comments posted, severity breakdown, model used, review duration) to
  a small store committed back into the consuming repo (e.g. a JSON/SQLite file under
  `.claude-pr-reviewer/`), with a simple generated summary (e.g. a markdown trend report). Fits
  entirely within the existing Action — no server, no database to operate.
- **3b (hosted dashboard, requires an infra decision):** graduate to a small persistent service —
  closest reference found is `middlewarehq/middleware` (Python/FastAPI + Postgres, 1.6k+ stars,
  open-source DORA-metrics platform) — once cross-repo/cross-team aggregation is actually needed.
  This requires choosing and paying for hosting and should be a deliberate, separate decision, not
  something bundled into a "build everything" pass.

Sequenced after Phase 2 because metrics are only worth collecting once review quality itself has
improved past the single-file baseline.

### Phase 4 — Multi-VCS support

Abstract `github_client.py` behind a small provider interface so the same review engine can run
against GitLab merge requests and Bitbucket pull requests, not just GitHub PRs. Confirmed via
research that no lightweight, actively-maintained Python library already does this — provider
clients exist per-platform (PyGithub, python-gitlab, atlassian-python-api) but nothing unifies
diff-fetching and inline-comment-posting across all three, so a small hand-rolled interface is the
right call rather than adding a heavy dependency.

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
- GitHub (current): `GET /repos/{owner}/{repo}/pulls/{pr}/files`
- GitLab: `GET /projects/:id/merge_requests/:iid/diffs` (paginated; the older `/changes` endpoint
  is deprecated)
- Bitbucket: `GET /repositories/{ws}/{repo}/pullrequests/{id}/diffstat` (structured, closest
  analog to GitHub's file list) or `/diff` (raw unified diff)

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

## Open decisions before building Phase 3b or beyond

- Phase 3b requires choosing and budgeting for hosting (even a small VM/PaaS instance is an
  ongoing cost commitment) — explicit go-ahead needed before starting it.
- Phase 4 requires deciding whether to support GitLab and Bitbucket simultaneously or stage them
  (GitLab first, since it's the harder/more complete design target).
- Phase 5's RAG component needs a decision on retrieval mechanism (simple keyword/recency
  matching vs. an embedding-based vector search) once there's enough Phase 3 data to retrieve
  from.
