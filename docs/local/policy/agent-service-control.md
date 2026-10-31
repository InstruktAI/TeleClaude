---
description: 'Where the live platform runs and how agents operate it: through `telec app` on the installation, from any directory, never through a checkout, raw host primitives, or edits inside the installation.'
visibility: 'public'
---

# Agent Service Control — Policy

## Rules

- **The live platform is the installation, not a checkout.** The platform runs from its installation under the XDG data directory (`local/projects/teleclaude/design/architecture/installation`); `telec app status` names the active release and where it lives. Live questions go through the installed tools — the global `telec`, `instrukt-ai-logs teleclaude`, `telec app status`. Code under construction runs only through a worktree's own `bin/telec` (`local/projects/teleclaude/spec/feature/agent_runtime/checkout-code-selection`).
- **Nothing inside the installation is edited.** Its releases are installed revisions; a change reaches them by being committed in a project, pushed, and installed.
- **Agents operate the installation through `telec app`, never through raw host primitives.** `telec app status`, `start`, `stop`, `restart`, `install [<revision>]` and `rollback` act on the installation from any directory and own every host-level service mechanic internally (`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`). In a project checkout the `make` lifecycle targets delegate to the installation and never operate a checkout.
- **Service definition deployment belongs to the installation.** The install act and `telec app start` deploy the launchd/systemd definitions, content-gated: a definition is rewritten and its unit reloaded only when the content rendered for the active-release pointer differs from what is deployed. Because the definitions address the pointer, switching releases leaves them unchanged.
- **Installing leaves the tmux server running.** The install act deploys no changed tmux server definition and names the deferred change instead, so the sessions the tmux server hosts survive its controlled restart. Deploying that definition is a deliberate re-run of the bootstrap, which ends those sessions.
- **Operating the live platform belongs to the install act and the installation inspector.** Any other agent runs a `telec app` verb that changes the installation — `start`, `stop`, `restart`, `install`, `rollback` — only when the human asks; `telec app status` and the platform logs are open to every agent. The `telec app` verbs and `telec config wizard` are that surface, and `telec app stop`/`telec app start` cover the case where a restart is insufficient.
- **A commit activates nothing; agents do not repeat an install.** A commit in a project changes nothing live (`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`). The channel reaction installs a pushed revision once; a revision no reaction installs is installed explicitly once, and never a second time.
- **Checks:** `telec app status`, `instrukt-ai-logs teleclaude --since <window> --grep <str>`.
- **Do not hand-invoke host service primitives directly** — the installation's lifecycle and service scripts, `launchctl`, `systemctl`, raw service bootout/bootstrap/unload/load. Route every service operation through `telec app`, which wraps these safely. This is a use-the-sanctioned-wrapper rule, not an approval gate.

### Graceful lifecycle operations

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- **Ordinary stop and restart prepare the observed daemon before replacing it.**
  `telec app stop` and `telec app restart` implement the accepted-work settlement contract
  (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`). They
  require positive preparation support and a drained acknowledgment belonging to
  the same process instance before the service-manager action. An observation
  timeout reports incomplete preparation and leaves that service in its explicit
  draining state; once its accepted work settles, the daemon completes the
  shutdown itself and the service manager relaunches it, so a timed-out restart
  owes no further call. A timed-out stop is relaunched the same way, and
  keeping the daemon down then takes another `telec app stop`. Forced termination
  remains an explicitly selected recovery action through `make kill`, which acts on the installation's daemon.

<!-- change:daemon-drain-ends-after-grace-window -->

- **Ordinary stop and restart prepare the observed daemon, then always complete.**
  `telec app stop` and `telec app restart` implement the accepted-work settlement contract
  (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`). They
  require positive preparation support and identify the process instance they
  prepare before any service-manager action. The daemon settles accepted work
  within its grace window and then ends, naming the work it interrupted; the
  stop or restart reports that work and continues to its service-manager action.
  A prepared instance that has neither acknowledged nor ended within the grace
  window and its teardown bound is terminated, and killed when termination does
  not end it, so neither verb leaves a daemon draining behind it. A stop keeps
  the daemon down; a restart starts it on the installed code. `make kill`
  remains the explicitly selected immediate forced termination, without a grace
  window, and acts on the installation's daemon.

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

- **Initial activation of a legacy runtime is explicit.** A daemon without the
  preparation protocol is reported as unsupported by ordinary stop/restart.
  The initial protocol activation uses an explicitly selected legacy activation
  path after positive process identification and observation of its unfinished
  work. That path reports legacy quiescence as observed, never as atomic draining,
  uses the legacy runtime's supported termination signal, waits for exit, and
  performs no forced termination on its observation timeout. It is unavailable
  for a runtime that supports preparation. The activating agent reads the known
  legacy limitation before selecting this path; the selector supplies no safety
  evidence or authorization (`general/policy/human-contract`).

  Immediate API effects can be running without the inspected durable work
  records, and new business requests can arrive between the observation and
  termination. Observed legacy quiescence neither closes admission nor proves
  that all effects have settled.

## Rationale

- An agent standing in a project cannot restart or reconfigure the live platform with code under construction when the command it uses does not depend on where it stands. Operating the installation through one location-independent surface removes that path rather than forbidding it.
- `telec app` is the safe, idempotent service interface: it encapsulates the platform-specific launchd/systemd mechanics, so whoever operates the installation needs no host-level judgement.
- Fixes reach the live platform forward: committed, pushed through CI and installed by the install act, whose inspector judges the result. Operating the daemon by hand outside that path is the out-of-the-ordinary case, so it happens when the human calls for it rather than as an agent's routine remedy.
- Content-gated deployment against a pointer keeps a release switch from bouncing services: without the content comparison every install would reload every unit, and without the pointer every install would rewrite them.
- Edits inside an installed release would be lost at the next install and would make the running code differ from any revision anyone reviewed.

## Scope

- Applies to all AI agents operating in this repository.

## Enforcement

- Reviewers and the integrator's log reading flag direct host-primitive invocation, lifecycle operations aimed at a checkout, and edits inside the installation; the remedy is the `telec app` verb.

## Exceptions

- None.

## See Also

- docs/local/adr/0041-agents-own-daemon-lifecycle-via-make.md
- docs/local/adr/0130-the-platform-runs-from-an-installation-not-its-project.md — why agents operate the installation through `telec app`.
- docs/local/design/architecture/installation.md
