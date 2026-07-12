---
description: The on-disk placement contract for $TELECLAUDE_HOME — every runtime-file category, where it lives, and the rule for placing a new file. The single authority agents consult before writing any file under the home directory.
visibility: internal
---

# TeleClaude Home Layout — Spec

## What it is

`$TELECLAUDE_HOME` (default `~/.teleclaude`) is the single tree holding a
machine's TeleClaude runtime files. This spec is the **placement authority**:
which category of file lives where, and the deterministic rule for placing a new
one. Its purpose is to remove the guess — so two agents never put the same kind
of file in two different places, and no agent invents a directory the layout does
not have.

`teleclaude/paths.py` enumerates the actual path constants. The division of
labor is strict: `paths.py` holds the values, this spec governs the decision.
This spec states placement rules and one canonical example per category; it does
**not** mirror the constant list. Consult it before adding any file under the
home directory.

## Canonical fields

### Categories and placement

<!-- planned-change:agent-usage-aware-dispatch -->

| Category                                                             | Location                            | Naming                      | Canonical example                          | Lifecycle                              |
| -------------------------------------------------------------------- | ----------------------------------- | --------------------------- | ------------------------------------------ | -------------------------------------- |
| Authored config & secrets                                            | home root                           | as published                | `teleclaude.yml`, `.env`                   | durable; backed up                     |
| Durable databases                                                    | home root                           | `<name>.db`                 | `teleclaude.db`, `mirrors.db`, `events.db` | durable                                |
| Durable structured state                                             | `state/`                            | `<name>.json`               | `tui_state.json`, `chiptunes_state.json`   | durable; rebuildable                   |
| Runtime control files — pidfile, lockfile, long-lived-process socket | home root, **flat**                 | `<service>.{pid,lock,sock}` | `cron_runner.pid`, `git-main.lock`         | survives process restart; never purged |
| Logs                                                                 | `logs/`                             | `<name>.log`                | `chiptunes_worker.log`                     | rotatable                              |
| Ephemeral scratch                                                    | `tmp/` or `$TMPDIR`                 | per use                     | `tmp/sessions/<id>/`                       | OS-cleanable                           |
| Deployed / authored artifacts                                        | named subdir                        | per artifact                | `commands/`, `shell/`, `docs/`, `people/`  | installed / authored                   |
| Per-project state                                                    | `<project>/.teleclaude/` (NOT here) | —                           | `deliveries/<slug>/`                       | per-project; gitignored                |

<!-- change:agent-usage-aware-dispatch -->

| Category                                                             | Location                            | Naming                      | Canonical example                          | Lifecycle                              |
| -------------------------------------------------------------------- | ----------------------------------- | --------------------------- | ------------------------------------------ | -------------------------------------- |
| Authored config & secrets                                            | home root                           | as published                | `teleclaude.yml`, `.env`                   | durable; backed up                     |
| Durable databases                                                    | home root                           | `<name>.db`                 | `teleclaude.db`, `mirrors.db`, `events.db` | durable                                |
| Durable structured state                                             | `state/`                            | `<name>.json`               | `tui_state.json`, `agent-usage.json`       | durable; rebuildable                   |
| Runtime control files — pidfile, lockfile, long-lived-process socket | home root, **flat**                 | `<service>.{pid,lock,sock}` | `cron_runner.pid`, `git-main.lock`         | survives process restart; never purged |
| Logs                                                                 | `logs/`                             | `<name>.log`                | `chiptunes_worker.log`                     | rotatable                              |
| Ephemeral scratch                                                    | `tmp/` or `$TMPDIR`                 | per use                     | `tmp/sessions/<id>/`                       | OS-cleanable                           |
| Deployed / authored artifacts                                        | named subdir                        | per artifact                | `commands/`, `shell/`, `docs/`, `people/`  | installed / authored                   |
| Per-project state                                                    | `<project>/.teleclaude/` (NOT here) | —                           | `deliveries/<slug>/`                       | per-project; gitignored                |

<!-- /planned-change:agent-usage-aware-dispatch -->

### The placement decision rule

Run this top to bottom; the first match wins:

1. **Authored or installed content** (config, secrets, databases, deployed
   artifacts)? → home root, or its named subdirectory (`commands/`, `shell/`).
2. **Durable structured state** the daemon reads or rebuilds as JSON? → `state/`.
3. **A pidfile, lockfile, or the control socket of a process?** → home root,
   flat, named `<service>.{pid,lock,sock}`. No subdirectory.
4. **Pure scratch**, recreated every run, safe to lose? → `tmp/` or `$TMPDIR`.

### The `/tmp` boundary

`/tmp` (the system temp dir) is reserved for **sockets a process recreates on
every startup**. The daemon's own API and MCP sockets (`/tmp/teleclaude-api.sock`,
`/tmp/teleclaude.sock`) live there because each daemon start remakes them, so a
periodic tmp-cleaner purge between starts is harmless.

Any file that must **survive a process restart** must live at the home root: every
pidfile, every lockfile, and the control socket of any **long-lived worker** — a
process designed to outlive daemon restarts. The macOS tmp-cleaner purges `/tmp`
entries untouched for ~3 days; a long-lived process's registry file placed there
is deleted out from under the live process, breaking liveness detection and
reattach. The distinguishing question is lifetime, not file type: a socket whose
owner recreates it each boot may stay in `/tmp`; a socket whose owner must persist
across boots belongs at the home root beside the pidfile.

### Invariants

- `$TELECLAUDE_HOME` is read exactly once at process startup by
  `teleclaude.runtime.config`, frozen into `RuntimeConfig.home`; every path
  constant derives from it. Relocation moves the entire tree transparently.
- The home tree is never tmp-purged — it is the durable location by definition.
- Per-service runtime control files are placed flat at the home root, one file
  per `<service>.<ext>`. There is no `run/`, `pids/`, `sockets/`, or any
  per-feature control-file subdirectory.
- Each path under `$TELECLAUDE_HOME` is defined once, in `teleclaude/paths.py`.
  Modules import the constant; they never re-declare the literal.

## Known caveats

- **Current deviation.** The daemon's single-instance pidfile
  (`teleclaude/daemon.py` → `teleclaude.pid`) lives at the install root, not
  under `$TELECLAUDE_HOME`; it is the one sanctioned exception.
- **No `run/` (or `pids/`, `sockets/`) subdirectory.** Pidfiles, lockfiles, and
  long-lived sockets are flat at the home root. A control-file subdirectory is the
  most common sprawl this spec exists to prevent.
- **No long-lived worker socket or pidfile in `/tmp`.** `/tmp` is only for sockets
  recreated on every process start.
- **No durable state in `/tmp` or a process-scoped tmpdir.** Durable state is
  `state/`; scratch is tmp.
- **No re-declared path literals.** Importing the `paths.py` constant keeps the
  two definition sites from drifting.
- **No constant-list mirror.** This spec is rules plus one example per category;
  `paths.py` is the enumerated source of truth.
- **Socket-path length.** macOS caps Unix-socket paths at 104 bytes. Home-root
  sockets (`~/.teleclaude/<service>.sock`) sit well within it for the default and
  typical custom homes; a pathologically deep custom `$TELECLAUDE_HOME` (>~95
  bytes) is the only case where this bites, and the lone reason a long-lived
  socket might stay in `/tmp`.

## See Also

- docs/project/spec/teleclaude-config.md — the typed configuration contract.
- docs/project/spec/agent-shell-path.md — the PATH contract for agent shells and the daemon.
