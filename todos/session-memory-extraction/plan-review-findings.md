# Plan Review Findings: session-memory-extraction

## Critical

### C1: Task 3 contradicts FR1's source-of-truth requirement

FR1 and `input.md` both say the delta reader must use the mirror system's
already-cleaned output and must not go back to raw transcript files. The plan's
Task 3 does the opposite: it fetches `metadata["transcript_path"]` from the
mirror and then calls `extract_structured_messages(transcript_path, ...)` on the
native transcript file.

That is not a localized wording issue. It changes the core technical path for
the todo and reintroduces the raw-transcript dependency the requirements
explicitly ruled out. The drafter needs to revise the FR1 approach so the plan
stays within the approved requirement boundary.

## Important

### I1: The test lane is not aligned with the repo's expected-failure spec workflow

`state.yaml` says test specs were already produced for this todo, and the
current worktree already contains an xfail-marked spec file at
`tests/unit/jobs/test_session_memory_extraction.py`. Task 10 still tells the
builder to create that file from scratch during build.

That misses the prepare-phase contract. The plan should point to the existing
expected-failure specs the builder will make green, not tell the builder to
author the spec file during build. The verification wording is also too
implementation-shaped in places, especially Task 1's proposed check for "no
reference to `send_keys_existing_tmux` or `/compact` in the module", which does
not prove the behavioral contract at a public boundary.

## Suggestion

- None.

## Resolved During Review

- Added `tests/unit/jobs/__init__.py`,
  `tests/unit/jobs/test_session_memory_extraction.py`, and
  `todos/session-memory-extraction/demo.md` to
  `state.yaml.grounding.referenced_paths` so the grounding metadata matches the
  files referenced by the current plan.
