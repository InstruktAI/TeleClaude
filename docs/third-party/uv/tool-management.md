---
description: uv tool install/upgrade/list semantics for machine-global CLI provisioning, including entrypoint-conflict behavior.
---

# uv Tool Management

## What it is

`uv tool` installs and manages machine-global command-line tools, each in its own
isolated environment, publishing their entrypoints into a shared executable directory
(`~/.local/bin` by default). It is the mechanism TeleClaude's installer uses to
provision machine-global Python CLIs.

The semantics below are what an installer must get right to keep a machine-global tool
both present and current. Each was verified against `uv 0.12.2` on macOS; where the
vendor prose and observed behavior differ, the divergence is called out.

## Install versus upgrade

`uv tool install <pkg>` on an **already-installed** tool is a **no-op**. It prints
`` `<pkg>` is already installed `` and exits `0` **without comparing versions**. A
presence check built on it silently tolerates an arbitrarily stale tool.

`uv tool install --upgrade <pkg>` (short `-U`) both installs when the tool is absent and
upgrades it when behind — one idempotent call covering both states. The flag is
documented as "Allow package upgrades, ignoring pinned versions in any existing output
file. Implies `--refresh`." Observed cost against an already-current package: ~1.3 s
wall clock, dominated by index resolution.

`uv tool upgrade <pkg>` **requires the tool to already be installed**. Against an absent
tool it fails with `` `<pkg>` is not installed; run `uv tool install <pkg>` to
install ``, so it cannot serve the fresh-host case on its own.

## Version constraints survive an upgrade

The vendor documentation states: _"Tool upgrades will respect the version constraints
provided when installing the tool."_ A tool first installed as `<pkg>==0.6.1` therefore
stays pinned across `uv tool upgrade`. Installing with a bare, unconstrained package
name is what makes "track latest" the standing behavior; an installer that wants latest
must not introduce a version specifier, and must expect a host previously pinned by hand
to need `--upgrade` (which ignores the recorded pin) rather than a plain upgrade.

## Entrypoint conflicts

Two packages can declare the same console-script name. uv refuses to resolve that
silently.

The vendor documentation states: _"Installation of tools will not overwrite executables
in the executable directory that were not previously installed by uv."_ **Observed
behavior is broader than that sentence**: uv also refuses to overwrite an entrypoint
owned by a _different uv-managed tool_. With a package owning `foo` already installed,
installing a second package that also declares `foo` fails:

```
error: Executable already exists: foo (use `--force` to overwrite)
```

The failing install exits **2**. The pre-existing owner keeps the symlink, and — the
part that matters for error handling — the newly requested package **does not appear in
`uv tool list`** afterwards, so the failure leaves no partial registration to detect.

`--force` overwrites the entrypoint. It re-points a shared symlink that other
applications on the host resolve; it does **not** uninstall the losing package.

An installer that calls `uv tool install` under `set -e` will therefore abort on exactly
the hosts that already have a conflicting owner. Conflict handling must be deliberate,
not incidental.

## Observing what owns an entrypoint

`uv tool list` is the inventory surface. It emits one line per package followed by its
entrypoints:

```
instruktai-python-logger v0.6.6
- instrukt-ai-log-setup
- instrukt-ai-logs
```

There is no JSON output mode. Useful flags include `--show-paths`, `--show-version-specifiers`,
and `--outdated`. Ownership of a given entrypoint is read by finding which package block
lists it — so a conflict is detected by the expected owner _not_ being the one that lists
it, which is the reliable test when the conflicting package's name is unknown or is not
resolvable from the public index.

## Isolating a rehearsal

`UV_TOOL_DIR` (tool environments) and `UV_TOOL_BIN_DIR` (published entrypoints) redirect
uv's own storage, which is enough to rehearse install, upgrade, and conflict behavior
without touching the real `~/.local/bin`.

They isolate **uv's storage only**. They do not sandbox what an installed tool _does_
when executed — a provisioning command run from an isolated tool dir still resolves the
real `$HOME` and writes real host state. Rehearsing an installer end-to-end needs
containment beyond these two variables.

## How these findings were established

The vendor page below supplies the executable-overwrite rule and the upgrade-constraint
behavior. Everything else — the `--upgrade` flag's presence and wording, the exact
conflict error and its exit code, the already-installed no-op, the not-installed upgrade
error, and the `uv tool list` output shape — was read from the shipped
`uv tool install --help`, `uv tool upgrade --help`, and `uv tool list --help` contracts
of **uv 0.12.2** and exercised against a scratch tool directory. Where the two disagree,
this document reports the observed behavior and says so, because the concepts page does
not enumerate every flag the CLI ships.

## Sources

- https://docs.astral.sh/uv/concepts/tools/ — tool concepts, executable-overwrite rule, upgrade constraint behavior.
