# DOR Assessment: refactor-agent-readiness

**Score:** 7/10 **Verdict:** `needs_work`
**Assessed at:** 2026-03-19T22:46:39Z **Commit:** `8bf72a0a6`

## Cross-artifact validation

- Plan-to-requirement fidelity: pass. The plan covers marker ownership, detector extraction,
  daemon consumption, readiness events, timeout handling, test updates, and quality gates
  in line with SC-1 through SC-8.
- Coverage completeness: pass. Each requirement and constraint has at least one task or
  verification path in the plan.
- Verification chain: needs work. The detector task still points to a spec set that does
  not prove marker lookup comes from `AgentName.prompt_marker` for the requested agent.

## DOR gates

1. Intent & success: pass. The goal, scope boundaries, success criteria, and timeout
   failure behavior are explicit in the requirements and match the input.
2. Scope & size: pass. Grounding against `teleclaude/core/agents.py`,
   `teleclaude/core/events.py`, `teleclaude/daemon_session.py`, and the targeted unit
   specs shows one coherent refactor on a single call chain, not a multi-todo program.
3. Verification: needs work. `tests/unit/core/test_agent_readiness.py` only exercises
   `agent_name="claude"`, so a detector with a second hardcoded marker table could still
   satisfy the cited tests while violating the metadata-owned-marker contract.
4. Approach known: pass. The plan follows existing code patterns: enum-owned agent
   metadata, typed event literals in `events.py`, and a daemon consumer that delegates
   readiness detection to a pure helper.
5. Research complete: pass. No new third-party dependencies or integrations are involved.
6. Dependencies & preconditions: pass. No new config surface or external-system access is
   required beyond existing tmux/session infrastructure; the todo is already on the roadmap.
7. Integration safety: pass. The refactor can land incrementally within the current
   daemon/session/test boundary and preserves the proven settle-then-marker algorithm.
8. Tooling impact: pass. Tooling and scaffolding are unchanged.

## Review-readiness assessment

- Code-quality lane: pass. The requirements and plan preserve boundary-purity and
  single-responsibility intent, and the implementation path is grounded in existing code.
- Testing lane: needs work. The open plan-review finding is valid and remains unresolved.
- Documentation/demo lane: pass. `demo.md` now carries concrete validation commands and a
  guided walkthrough tied to the expected delivery.
- Security/config lane: pass. No new config, auth, or external-surface changes are introduced.

## Blockers

- `verification: spec-delivered tests do not yet prove wait_for_agent_ready resolves markers from AgentName.prompt_marker for the requested agent`

## Notes

- Domain grounding was loaded through `telec docs index` and `telec docs get` using a
  temporary minimal project root because the repo-root `telec docs index` path currently
  fails project-config validation in this checkout.
- No artifact content was auto-remediated during gate scoring; the report records the
  current blocker rather than silently extending scope.
