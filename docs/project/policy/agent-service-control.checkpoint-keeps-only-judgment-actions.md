---
description: 'How agents operate the daemon: through the make targets (never raw host primitives); a directed make target is mandatory; deterministic maintenance runs at the commit boundary.'
visibility: 'public'
---

# Agent Service Control — Policy

## Rules

- **Agents operate the daemon through `make` targets, never through raw host primitives.** The `make` targets own every host-level service mechanic internally: `make install` deploys the launchd/systemd service definitions, and `make start`/`stop`/`restart`/`kill`/`status` operate the services already deployed.
- **Service definition deployment belongs to `make install`; `bin/daemon-control.sh` operates lifecycle only.** Deployment is content-gated — a definition is rewritten and its unit reloaded only when the content rendered from the template differs from what is deployed. An unchanged definition leaves its running service untouched, and a corrected template reaches every host on that host's next `make install`.
- **Lifecycle and setup `make` targets are first-class agent commands:** `make restart`, `make start`, `make stop`, `make status`, `make install`, alongside `telec config wizard` and `telec projects init`. `make stop`/`make start` cover the case where a restart is insufficient.
- **A directed `make` target is mandatory.** The deterministic maintenance a commit's changed paths owe — `make install` after setup changes, `make restart` after daemon-code changes — is performed at the commit boundary rather than asked of an agent (`project/spec/feature/integration/post-commit-maintenance`). The integrator's advance of repo-root `main` is the boundary that mechanism does not reach, so its owed targets are still directed at the integrator holding that checkout (`project/design/architecture/checkpoint-system`, Invariant 19). Wherever a target is directed at an agent, that agent never refuses, defers, or substitutes it on the basis of this policy — even when the target internally deploys or reloads a service definition.
- **Checks:** `make status`, `instrukt-ai-logs teleclaude --since <window> --grep <str>`.
- **Do not hand-invoke host service primitives directly** — `bin/daemon-control.sh`, `bin/init/install_services.sh`, `launchctl`, `systemctl`, raw service bootout/bootstrap/unload/load. Route every service operation through the `make` targets, which wrap these safely. This is a use-the-sanctioned-wrapper rule, not an approval gate.

## Rationale

- The `make` targets are the safe, idempotent service interface: they encapsulate the platform-specific launchd/systemd mechanics, so agents need no host-level judgement and routine service operations need no human gate. Routing every operation through them limits accidental downtime while keeping checkpoint-required operations unblocked.

- Deployment belongs with the target that already runs on every setup change, and it is safe there only because it is content-gated: without the content comparison, the `make install` every setup change triggers would bounce every service on every run. Gating on existence instead of content is what lets a corrected template sit undeployed indefinitely on a host that already has the old file.

## Scope

- Applies to all AI agents operating in this repository.

## Enforcement

- An agent that refuses, defers, or substitutes a directed `make` target is in violation.
- Review agent logs for direct host-primitive invocation (`launchctl`, `systemctl`, raw `bin/daemon-control.sh`); route those operations through the `make` targets instead.

## Exceptions

- None.

## See Also

- docs/project/adr/0041-agents-own-daemon-lifecycle-via-make.md
