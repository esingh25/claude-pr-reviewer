# CLAUDE.md

Notes captured from mistakes made while building this repo, so future work here doesn't repeat them.

## Git/GitHub setup on this machine

`gh repo create --source=. --remote=origin` defaults to an SSH remote here, but pushing over SSH
fails with "Host key verification failed" (github.com isn't in this machine's `known_hosts`).
Fix: `git remote set-url origin https://github.com/<owner>/<repo>.git` — `gh`'s stored credentials
work over HTTPS with no extra setup. Don't spend time debugging SSH known_hosts for this; just
switch the remote to HTTPS immediately if a push fails with that error.

## Ruff / lint conventions

- Target is Python 3.11: use `enum.StrEnum`, not `class X(str, Enum)` (ruff rule `UP042`).
- Line length is capped at 100 (see `pyproject.toml`). Wrap long `assert`/function-call lines as
  you write them — especially in tests with long fixture/helper names — rather than writing long
  one-liners and fixing lint afterward.

## Validating LLM-generated structured output (`claude_client.py`)

A successful `json.loads()` does not mean the shape is right. Before iterating into a parsed
Claude response, explicitly check:
- the top-level value is a `dict` (not a bare list/string/number)
- the field you're about to iterate (`comments`) is a `list`
- each element you're about to call `.get()` on is itself a `dict`

Any of these being wrong raises `AttributeError`/`TypeError`, not `ClaudeReviewError`, and that
propagates uncaught past exception handlers that only catch `ClaudeReviewError` — crashing the
whole run instead of just skipping one file. Raise `ClaudeReviewError` explicitly for all three
shape checks so the existing per-file graceful-degradation logic in `review_engine.py` actually
catches it.

## Acting on review feedback

When a code/security review recommends a specific mitigation (e.g. "sanitize `@mentions` before
posting to GitHub"), implement that exact mechanism — not just a thematically related fix. The
first hardening pass on this repo added prompt-injection language to the system prompt plus
comment length/count caps, but did *not* add the `@mention`/`#ref` sanitization the security
review explicitly called out as the fix — leaving that finding actually unresolved until a
follow-up bounty-hunter pass caught the gap. Cross-check each concrete recommendation against the
diff before marking a review item done, don't just address the general theme.
