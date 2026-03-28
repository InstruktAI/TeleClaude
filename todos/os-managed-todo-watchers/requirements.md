# os-managed-todo-watchers — Requirements

## Problem Statement

The daemon-owned `TodoWatcher` runs watchdog/FSEvents threads in-process,
causing refresh amplification and watcher-thread pressure that manifests as
API loop-lag hang dumps. File observation must move out of the daemon and
into OS-managed watcher services, following the ownership model already
established for docs sync.

## Success Criteria

1. No daemon thread or async task performs filesystem observation for todo or
   worktree changes.
2. An OS-managed watcher service per project detects relevant todo/worktree
   filesystem changes and notifies the daemon.
3. The daemon remains the sole authority for semantic effects: stale-preparation
   invalidation, todo snapshot recomputation, digest comparison, cache updates,
   and TUI/WebSocket fan-out.
4. `telec init` installs the todo watcher service on supported platforms with
   no manual steps beyond re-running init.
5. Watcher-to-daemon communication is authenticated, local-only, and does not
   use the generic dynamic webhook subsystem.

---

## R1 — Watcher Process Behavior

The watcher process runs as a long-lived OS-managed service (one per project)
and is responsible for detecting filesystem changes and reporting relevant paths
to the daemon.

### R1.1 — Observation Scope

The watcher observes exactly one project root recursively.

### R1.2 — Path Normalization

All reported paths are project-relative and use POSIX-style separators,
regardless of the host OS filesystem representation.

### R1.3 — Move Event Handling

For filesystem move/rename events, both the source and destination paths are
evaluated against the path filter.

### R1.4 — Noise Filtering

The watcher ignores hidden files/directories and temporary/editor artifacts
(swap files, backup files, tilde-suffixed files) before path matching.
`[inferred]` The specific artifact categories are inferred from the input's
"hidden/temp/editor noise" directive; the builder determines the exact filter
set from codebase conventions.

### R1.5 — Path Allowlist

Only changes matching the following patterns are reported:

**File patterns:**

- `todos/*.yaml`
- `todos/*/*.md`
- `todos/*/*.yaml`
- `todos/_icebox/icebox.yaml`
- `todos/_icebox/*/*.md`
- `todos/_icebox/*/*.yaml`
- `trees/*/todos/*/*.md`
- `trees/*/todos/*/*.yaml`

**Directory events** (create, delete, move):

- `todos/<slug>`
- `todos/_icebox/<slug>`
- `trees/<slug>`
- `trees/<slug>/todos/<slug>`

These are reported because directory existence changes affect todo resolution.

### R1.6 — Batching and Debounce

Matching paths are accumulated over a short debounce window and delivered as a
single notification per window. Individual file events are not sent one-by-one.

### R1.7 — No Semantic Processing

The watcher never performs todo recomputation, snapshot assembly, digest
comparison, or any TUI/WebSocket work. It reports paths only.

---

## R2 — Daemon Internal Route

The daemon exposes a dedicated internal route for receiving watcher
notifications. This route is separate from the generic webhook surface.

### R2.1 — Authentication

The route authenticates requests using a watcher-specific secret, not the
standard session-based or terminal-login caller identity. Watcher services do
not have tmux or terminal context.

### R2.2 — Project Trust Verification

The route verifies that the `project_root` in the notification belongs to a
trusted directory before processing.

### R2.3 — Server-Side Path Re-filtering

The daemon re-applies the same path allowlist (R1.5) server-side against the
reported `changed_paths`. `[inferred]` This provides defense-in-depth against a
compromised or misconfigured watcher reporting arbitrary paths.

### R2.4 — Stale Preparation Invalidation

If any of the re-filtered paths affect stale-preparation logic, the daemon
triggers invalidation for the affected scope.

### R2.5 — Single Recomputation Per Notification

The daemon recomputes the todo snapshot for the affected project exactly once
per notification batch, not once per changed path.

### R2.6 — Digest-Gated Emission

The daemon compares the new snapshot digest against the previous digest. Cache
updates and WebSocket emissions occur only when the digest has changed. Matching
changes that do not alter the assembled snapshot produce no downstream effect.

### R2.7 — Transport

Watcher notifications travel over the existing local Unix-socket API, not over
the TCP/public surface.

---

## R3 — Watcher Secret Management

### R3.1 — Secret Generation

`telec init` generates a watcher-specific secret for each project during service
installation.

### R3.2 — Secret Storage

The secret is stored persistently so the daemon can verify incoming requests.
`[inferred]` The storage location and mechanism are implementation concerns.

### R3.3 — Secret Injection

The secret is injected into the OS service environment so the watcher process
can include it in requests without filesystem reads at runtime.

### R3.4 — Rejection on Missing or Invalid Secret

The internal route rejects requests with a missing or invalid secret. The
rejection must not leak information about valid secrets.

---

## R4 — Service Installation via `telec init`

### R4.1 — macOS Installation

On macOS, `telec init` installs a launchd agent that runs the todo watcher
process for the project. The service is kept alive by the OS and starts at load.

### R4.2 — Linux Installation

On Linux, `telec init` installs a systemd `--user` service that runs the todo
watcher process for the project. The service is kept alive by systemd.

### R4.3 — No Use of Coarse OS Path Units

The feature must not use launchd `WatchPaths` or `systemd.path` for todo
monitoring. These mechanisms are too coarse for deep recursive observation of
todo/worktree directories.

### R4.4 — Platform Scope

The initial implementation covers macOS and Linux. BSD/kqueue support is
explicitly out of scope.

### R4.5 — Idempotent Installation

Re-running `telec init` on a project that already has a todo watcher service
installed replaces the service cleanly without leaving stale artifacts.
`[inferred]`

### R4.6 — One Service Per Project

Exactly one todo watcher service is installed per project. Multiple projects
each get their own independent service.

---

## R5 — Daemon TodoWatcher Removal

### R5.1 — No Daemon-Owned File Observation

After migration, the daemon performs no filesystem observation for todo or
worktree changes. The daemon does not retain a fallback file-watching mechanism.

### R5.2 — Retirement of In-Process Watcher

The current in-process watcher (watchdog/FSEvents observer, event handler,
debounce loop, and daemon lifecycle integration) is removed entirely.

---

## R6 — Rollout Safety

### R6.1 — Additive Before Removal

The new watcher endpoint and service installation are functional before the
daemon-owned watcher is removed. The removal is a separate step, not
simultaneous with introduction.

### R6.2 — Migration Path

Existing projects gain the new watcher service by re-running `telec init`. No
separate migration command is required. `[inferred]`

---

## R7 — Allowlist Design Rationale (Non-Functional)

The path allowlist (R1.5) is intentionally tight on per-slug top-level `*.md`
and `*.yaml` files. It includes `delivered.yaml` via `todos/*.yaml` even though
delivered items are not currently assembled by default — delivered state is part
of the todo lifecycle and may affect staleness or UI computation in the future.
Digest-gated emission (R2.6) prevents this broader scope from causing
unnecessary churn.

The watcher scope should only be widened when the UI or semantic layer actually
consumes deeper nested todo assets.

---

## Review-Awareness Notes

- `telec init` behavior changes (R4) imply that the CLI help text for `telec init`
  should be updated to reflect todo watcher service installation alongside the
  existing docs sync functionality. `[inferred]`

---

## Deferred / Out of Scope

- **TUI refresh volume re-evaluation** — deferred until after watcher ownership
  is fully migrated.
- **BSD/kqueue support** — deferred unless explicitly required.
- **Deeper nested todo asset watching** — deferred until the UI consumes them.
- **Todo splitting assessment** — this feature touches multiple subsystems
  (watcher process, daemon route, auth, service installation, watcher removal)
  but they form a single coherent behavior: OS-managed watching replaces
  daemon-owned watching. The rollout is additive and sequenced, but the pieces
  are not independently valuable — partial delivery leaves the architecture in
  a transitional state. Whether this warrants splitting into dependent todos is
  a draft-phase decision that should be grounded in actual implementation size
  estimation.
