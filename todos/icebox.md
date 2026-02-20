# Icebox

Acknowledged work that has no active priority. Items here are valid but parked.
Reviewed periodically — promote back to [roadmap.yaml](./roadmap.yaml) when priority changes.

---

## Agent File Locking Heartbeat

Agent-level file locking to prevent same-file collisions on `main` with deterministic contention behavior: heartbeat on contention, retry after 3 minutes, then halt with precise blocker report if still locked. Commit ownership remains with agent.

## Code Context Annotations

Code annotation extraction and doc snippet integration work. Parked behind core identity/streaming/web delivery.

## Code Context Auditor

Drift-auditing layer for context annotations. Depends on code-context-annotations and is parked with it.

## Bidirectional Agent Links

Agent-to-agent chat/link system. Nice-to-have, not on the near-term product path.

## GitHub Maintenance Runner

Periodic GitHub bug triage and automated bugfix PR flow in a dedicated maintenance worktree. Useful operational automation, but postponed behind current core product delivery priorities.

## TDD Enforcement (Single Test Contract)

Strict TDD enforcement initiative (upfront approved test contract + builder/fixer test immutability) is parked to avoid workflow disruption right now. Revisit when bandwidth is available for process hardening.
