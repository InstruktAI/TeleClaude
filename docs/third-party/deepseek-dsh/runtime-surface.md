---
description: DeepSeek Harness (dsh) CLI surface — launcher flags, harness home, profile directories, plugin management, the plugin compatibility check, and the headless one-shot invocation, as observed from the installed binary.
---

# DeepSeek Harness (dsh) — Runtime Surface

## What it is

`dsh` boots a **profile**: an ordered stack of plugin-bundle patch layers under
the operator's own overrides. The launcher owns a small flag set; arguments
after those flags reach the booted profile's app.

**Evidence basis.** Everything below was read from the installed binary at
version `0.2.0-rc.2`: its `--help` output, the headless profile's `--help`, the
error emitted for an absent profile, the installed package sources of the
launcher, `dsh-home-paths`, `dsh-app-boot` and the plugin command, and the
on-disk layout of an installed harness home. No vendor documentation was
consulted; see "Known caveats" for what that leaves unestablished.

## Canonical fields

### Launcher flags

Quoted from `dsh --help`:

| Flag                            | Help text                                                                    |
| ------------------------------- | ---------------------------------------------------------------------------- |
| `--profile <name>`              | the profile under `$DSH_HOME/profiles` to boot                               |
| `--from-default-profile <name>` | initialize a new custom profile from a shipped profile template              |
| `--patch <path>`                | extra patch-list overlay applied after the profile layer (repeatable)        |
| `--dump-config`                 | print the composed profile tree and exit                                     |
| `--dump-config-schema`          | print JSON Schema for profile entries and patches without mounting           |
| `--dump-default-config`         | print the profile tree without its user layer or `--patch` overlays and exit |
| `-V, --version`                 | output the version number                                                    |

The usage line is `dsh [--profile] <name> [options] [app-args...]`; a bare first
argument names the profile (`dsh web` boots the `web` profile). Positional
arguments after the launcher flags are "arguments for the booted profile's
app", discoverable per profile via `dsh --profile <name> --help`.

The config-schema description states that expression results, service
dependencies and plugin startup checks "still require runtime validation": a
config dump composes the tree but is not evidence that every plugin mounts.

### Harness home

The home resolves, highest precedence first, from an explicit configured path,
then `$DSH_HOME`, then `~/.dsh`. A blank or whitespace-only `$DSH_HOME` counts as
unset. The harness keeps all of its user data under this one root. An installed
home holds, among others:

| Entry               | Role                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------- |
| `profiles/<name>/`  | one directory per profile                                                             |
| `cordis.patch.yml`  | machine-local patch layer, applied to every profile after the profile's own patch     |
| `.credentials.yaml` | account credentials                                                                   |
| `.agent-presets/`   | agent presets; a preset managed by the TUI carries a `.dsh-tui-managed.json` marker   |
| `sessions/`         | persisted sessions                                                                    |
| `storages/`         | runtime stores, such as `workspace.json` and `checkpoints.json`                       |
| `hooks.json`        | global hook layer read by the dsh-hooks plugin (see `third-party/deepseek-dsh/hooks`) |
| `logs/`             | runtime and plugin logs                                                               |

### Profile directory

A profile directory is a pnpm project. Its `package.json` lists the profile's
packages under `dependencies` and the ordered bundle list under
`dsh.profile.bundles`. Beside it sit `pnpm-lock.yaml`, `pnpm-workspace.yaml`,
`cordis.yml`, the profile's own `cordis.patch.yml`, a `.plugin-manager/`
directory, `node_modules/`, and, once an exemption has been recorded,
`compatibility.json`.

### Profiles must already exist

A profile name that does not resolve is a hard boot error rather than an
auto-initialization:

```
Error: dsh: profile "<name>" does not exist; create it with 'dsh plugin --profile <name> add <package>'
```

`dsh plugin --profile <name> …` initializes a missing profile directory from
the shipped template of that name or the default bundle list, except for the
reserved `desktop` profile: a plugin command on `desktop` fails until the
Desktop application has initialized that profile itself. Other profile names
are operator-chosen.

### Plugin management

`dsh plugin --profile <name> <args…>` forwards its arguments to pnpm (11.15.1
observed) in the profile directory, under a lock on the profile's
`package.json`, with three exceptions the launcher handles itself:

- `allow-version <package@version> --dsh-version <exact> --accept-risk` records
  an exact-version compatibility exemption in the profile's
  `compatibility.json`;
- `revoke-version <package@version> --dsh-version <exact>` removes one;
- `version-exemptions` prints the recorded exemptions as JSON.

A package operation that would install a plugin incompatible with the
installed runtime fails, and the launcher prints the `allow-version` command
that would accept the risk. Adding a git-hosted plugin can fail until pnpm is
allowed to run that package's build, through `allowBuilds` in the profile's
`pnpm-workspace.yaml`.

### Plugin compatibility check

At startup and in the plugin manager, a plugin is checked against the running
runtime version through its manifest's `peerDependencies`:

- only peers named `@deepseek-ai/dsh` or `@deepseek-ai/dsh-*` are checked;
  peers on any other package, the bundled libraries included, are ignored;
- a `workspace:^`, `workspace:~` or `workspace:*` range stands for the runtime
  version itself;
- a range holds when `semver.satisfies(runtimeVersion, range, { includePrerelease: true })`
  is true, so a prerelease runtime can satisfy a range that names no
  prerelease;
- an incompatible plugin is exempted only by an exemption recorded for its
  exact `name@version` and the exact runtime version.

### One-shot invocation

The `headless` profile is the one-shot surface. Quoted from its help:

```
Usage: dsh --profile headless [options] [task...]

Answer one task and exit; the answer goes to stdout and diagnostics to stderr.

Arguments:
  task               the task text; multiple words are joined by spaces, and `-`
                     reads stdin

Options:
  --json             write newline-delimited run events to stdout instead of the
                     final message
  --session-id <id>  adopt the persisted Session with this id; an unknown id is
                     an error
  -h, --help         show this help
```

`--json` changes the output to run events; no option takes an output schema.

### Resume

`--resume <session>` is an app argument, not a launcher flag. `dsh --help`
documents this positionally: `dsh tui --resume <session>` — "arguments after the
launcher flags reach the app".

## Known caveats

Established only from the installed binary's own help, error output and package
sources. The following are **unestablished here** and must not be inferred from
this snippet:

- The schema and merge semantics of `--patch` payloads.
- The shape of the `--json` run events.
- Which entries of the harness home the runtime reads at boot beyond those
  listed, and whether a later release adds others.
- Any sandbox or permission behavior; no such flag appears on the launcher.

## See Also

- docs/third-party/deepseek-dsh/hooks.md — the dsh-hooks executor's event and decision contract.
