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

<!-- planned-change:adaptive-usage-routing -->

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

<!-- change:adaptive-usage-routing -->

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

<!-- /planned-change:adaptive-usage-routing -->

### Documentation in the home

The home holds two kinds of documentation location, and they never overlap:

- **`docs/` is the published generation.** It holds every published domain's
  snippets under `<domain>/…` and the published half of each participating
  person and company under `people/<slug>/…` and `companies/<slug>/…`.
  Publication rebuilds it from recorded commits; nothing is authored there, and
  no home's local half ever enters it.
- **`people/<slug>/` and `companies/<slug>/` are documentation homes.** Each
  carries its own `teleclaude.yml` and the two halves every documentation home
  has (`general/spec/snippet-authoring-schema`): `docs/global/<taxonomy>/…`,
  which publication copies into `docs/people/<slug>/…` or
  `docs/companies/<slug>/…`, and `docs/local/<taxonomy>/…`, which is served in
  place from the local index beside it (`docs/local/index.yaml`, a build output).

A person's or company's authored snippet is placed in that tier's home —
`docs/global` when it is published, `docs/local` when it is not — and is never
written under `docs/`.

### The placement decision rule

Run this top to bottom; the first match wins:

1. **Authored or installed content** (config, secrets, databases, deployed
   artifacts)? → home root, or its named subdirectory (`commands/`, `shell/`).
2. **Durable structured state** the daemon reads or rebuilds as JSON? → `state/`.
3. **A pidfile, lockfile, or the control socket of a process?** → home root,
   flat, named `<service>.{pid,lock,sock}`. No subdirectory.
4. **Pure scratch**, recreated every run, safe to lose? → `tmp/` or `$TMPDIR`.

### Template-installed files

<!-- planned-change:help-desks-as-deployment-output -->

Machine installation writes TeleClaude's templates into the home, into every
declared person and company home, and into every enabled help desk among them
(`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`):

- Each home's `AGENTS.master.md`, and each help desk's, is refreshed from its
  template on every installation, so an edit made in place does not last
  (`general/policy/agent-artifact-governance`).
- A person's or company's local baseline manifests under `docs/local/` are
  created once and then belong to that home.
- The platform help desk is the home's `help-desk/`; a company's help desk is
  `companies/<slug>/help-desk/`. Each is a folder of its home, never a
  repository of its own.
- The home's `docs/` receives no template.

<!-- change:help-desks-as-deployment-output -->

TeleClaude's templates reach the home, every declared person and company home,
and every enabled company help desk among them in two ways
(`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`):

- Machine installation writes the home's repository layer: its `.gitignore`
  retained-set declaration and its projection-only editor settings. A person's
  or company's local baseline manifests under `docs/local/` are created once,
  then belong to that home.
- Convergence, at the home's commit-boundary maintenance and in `telec sync`,
  seeds each person's and company's `AGENTS.master.md` and each enabled company
  help desk from their templates while they are absent. A seeded master then
  belongs to its home, whose history records it
  (`general/policy/agent-artifact-governance`).
- The home's root `AGENTS.master.md` and the platform help desk have no
  template; they are authored in the home.
- The platform help desk is the home's `help-desk/`; a company's help desk is
  `companies/<slug>/help-desk/`. Each is a folder of its home, never a
  repository of its own.
- The home's `docs/` receives no template.

<!-- /planned-change:help-desks-as-deployment-output -->

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

### Home entrypoints

The home masters are a fixed set: the home root's `AGENTS.master.md`, the
platform help desk's `help-desk/AGENTS.master.md`, each declared person's and
company's root master, and each declared company's
`companies/<slug>/help-desk/AGENTS.master.md`. The home's retained set admits
every one of them, so an edit to a master is committed in the home's history
and owes the publication that inflates it
(`local/projects/teleclaude/spec/feature/context/agents-master-inflation`). A master
anywhere else in a home, including under a home's docs, is not compiled, so no
generated entrypoint ever lands in a retained subtree. The `AGENTS.md` beside
each master is generated: it is never retained, never edited, and never a
placement target. The home holds no generated `CLAUDE.md`.

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
- Machine installation owns canonical-checkout symlinks for repository-owned
  runtime support. It preserves an already-correct link, replaces only a known
  legacy generated directory, and refuses a target whose unexpected contents
  would otherwise be discarded.

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

- docs/local/spec/teleclaude-config.md — the typed configuration contract.
- docs/local/spec/agent-shell-path.md — the PATH contract for agent shells and the daemon.
