---
id: 'project/policy/tmux-session-env-propagation'
type: 'policy'
scope: 'project'
description: 'TMUX session environment is not a generic propagation channel for agent-session context or automation behavior.'
---

# Tmux Session Env Propagation — Policy

## Required reads

- @docs/project/spec/session-identity-truth.md
- @docs/project/spec/identity-and-auth.md
- @docs/project/design/architecture/layer-ownership.md

## Rules

- The TMUX session environment is not a generic propagation channel for agent-session context or automation behavior.
- Do not introduce a new environment variable into a TMUX session unless a documented runtime contract defines its producer, consumer, semantics, and validation path.
- Do not rely on TMUX-injected environment variables being visible to, accepted by, or acted on by agent sessions unless that behavior is already an explicit supported contract in this repository.
- Environment variables used for daemon-owned bootstrap, wrappers, auth, theming, or other runtime machinery are allowed only when their consuming path is explicit and documented.
- When automation needs additional data to reach an agent session, extend the owning contract or injection path instead of adding an ad hoc TMUX environment variable.
- Agent-facing prompts, artifacts, and project documentation must not teach agents to depend on newly injected TMUX environment variables as a context mechanism.

## Rationale

- Agent sessions do not provide a reliable generic environment surface for arbitrary TeleClaude propagation.
- Ad hoc TMUX environment propagation creates false assumptions about what agent sessions or automation layers will actually honor.
- Explicit contracts preserve legitimate operational use of environment variables without turning TMUX env into a speculative context bus.

## Scope

- Applies to daemon bootstrap, tmux session creation, wrappers, runtime automation, and agent-facing project documentation in this repository.
- Applies specifically to TMUX-session environment propagation as an automation mechanism.
- Does not ban ordinary environment-variable use for configuration, secrets, or already documented runtime contracts.

## Enforcement

- Review any new TMUX environment injection for an explicit documented contract and an identified consumer.
- Reject changes that add TMUX environment variables solely on the assumption that an agent session or automation layer will accept them.
- When a new TMUX environment contract is justified, document it in the owning project spec or policy in the same change.

## Exceptions

- None. New TMUX environment propagation requires an explicit documented contract before it is introduced.
