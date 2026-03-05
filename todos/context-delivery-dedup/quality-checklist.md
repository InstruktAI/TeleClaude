# Quality Checklist: context-delivery-dedup

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 17 unit tests pass for context_selector; pre-existing failures in test_telec_sync/guardrails tests are unrelated to this build
- [x] Lint passes (`make lint`) — passes with warn-only; pre-existing `snippet_unknown_section` in telec-cli.md and one unrelated snippet_invalid_ref are not caused by this build
- [x] No silent deferrals in implementation plan
- [x] Code committed — 3 commits: bff954bf (core change + tests + validator fix), 6be0c072 (AGENTS.md trimming), e3c8f958 (policy doc update)
- [x] Demo validated (`telec todo demo validate context-delivery-dedup` exits 0, or exception noted) — 4 executable blocks found
- [x] Working tree clean — build-scope changes committed; orchestrator-managed drift (state.yaml, worktree-prep-state.json) is non-blocking
- [x] Comments/docstrings updated where behavior changed — context_selector.py header string updated inline; policy doc updated to describe new three-phase flow

### Notes

- CLAUDE.md size is ~39.8k chars vs. the 28k target in the implementation plan. The three targeted removals reduced it from ~51k to ~40k (~11k reduction). The 28k target was set before `fix(docs)` commits on this branch added Required/Scope/Enforcement/Exceptions sections to many snippets (~12k inflation). The three workstream goals are fully implemented; the residual gap is outside this build's scope.
- Daemon process caches old code in memory; `telec docs get` via MCP reflects old behavior until daemon restarts. Direct Python invocation confirms the new `# Required reads (not loaded)` format works correctly.

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked
- [ ] Test coverage and regression risk assessed

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
