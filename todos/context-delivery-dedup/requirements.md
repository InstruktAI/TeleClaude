# Requirements: context-delivery-dedup

## Goal

Eliminate duplicate context token delivery when agents call `telec docs get` multiple times
in a session, and reduce the global AGENTS.md baseline from ~46k to ~24k chars.

## Scope

### In scope

1. **Context delivery dedup** — Change `build_context_output()` default behavior: list required
   reads as IDs in the output header instead of expanding their content inline. The agent sees
   the dependency list and fetches only what it doesn't already have.
2. **AGENTS.md trimming** — Three targeted reductions to the global baseline:
   a. Remove Agent Direct Conversation procedure from `baseline.md` (agents load on-demand).
   b. Trim Telec CLI spec: remove `telec sessions` and `telec sessions send` expanded sections.
   c. Replace baseline index snippet list with a one-liner instruction.

### Out of scope

- Session-level dedup caching or exclude-list mechanisms (the agent IS the dedup engine).
- Changes to `_resolve_requires()` internals — it still resolves the full dependency tree.
- Changes to `telec docs index` behavior.
- Refactoring third-party doc output in `build_context_output()`.

## Success Criteria

- [ ] `telec docs get snippet-a snippet-b` outputs only snippet-a and snippet-b content,
      with a `# Required reads (not loaded): snippet-c, snippet-d` header line listing deps.
- [ ] Subsequent `telec docs get snippet-f` (which also requires snippet-c) lists snippet-c
      in the required reads header without expanding it.
- [ ] Agent calling `telec docs get snippet-c snippet-d` explicitly still gets full content.
- [ ] Global `~/.claude/CLAUDE.md` is under 28k chars after trimming.
- [ ] Agent Direct Conversation is still available via `telec docs get general/procedure/agent-direct-conversation`.
- [ ] `telec sessions -h` still works at runtime for agents needing session command details.
- [ ] All existing tests pass (with format assertion updates where needed).
- [ ] `telec sync` regenerates AGENTS.md correctly after source changes.

## Constraints

- No new flags or arguments to `telec docs get`. This is a default behavior change.
- The `_resolve_requires()` function must still compute the full dependency tree (needed for
  the ID listing). Only the output rendering changes.
- The header format changes from `# Auto-included (required by the above): ...` to
  `# Required reads (not loaded): ...`. Any downstream parsing must be updated.
- Baseline doc sources live in `docs/global/baseline.md` and `docs/global/baseline-progressive.md`.
  The telec CLI spec source is `docs/global/general/spec/tools/telec-cli.md`.
  All are expanded during `telec sync` — edit sources, not generated output.

## Risks

- Agents that relied on auto-expansion to get dependency content in a single call will now
  need a second call. Mitigation: the header explicitly lists what's needed, and the extra
  call is 1-2 seconds vs thousands of duplicate tokens over a session.
- Parsing breakage if any script greps for `Auto-included`. Mitigation: grep confirms only
  `context_selector.py:738` uses that string; no tests or scripts depend on it.
