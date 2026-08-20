---
description: DeepSeek Harness (dsh) CLI surface — launcher flags, profile booting, and the headless one-shot invocation, as observed from the installed binary.
---

# DeepSeek Harness (dsh) — Runtime Surface

## What it is

`dsh` boots a **profile**: an ordered stack of plugin-bundle patch layers under
the operator's own overrides. The launcher owns a small flag set; arguments
after those flags reach the booted profile's app.

**Evidence basis.** Everything below was read from the installed binary at
version `0.1.0-rc.7` — `dsh --help`, `dsh --profile headless --help`, and the
error emitted for an absent profile. No vendor documentation was consulted; see
"Known caveats" for what that leaves unestablished.

## Canonical fields

### Launcher flags

Quoted from `dsh --help`:

| Flag                    | Help text                                                             |
| ----------------------- | --------------------------------------------------------------------- |
| `--profile <name>`      | the profile under `$DSH_HOME/profiles` to boot                        |
| `--patch <path>`        | extra patch-list overlay applied after the profile layer (repeatable) |
| `--dump-config`         | print the composed profile tree and exit                              |
| `--dump-default-config` | print the profile tree without its user layer or `--patch` overlays   |
| `-V, --version`         | output the version number                                             |

Sub-commands: `web` (documented as an alias of `--profile web`) and
`plugin [options] [args...]`, which "manage a profile's plugins by forwarding
the remaining arguments to pnpm in the profile directory".

Positional `args` are "arguments for the booted profile's app", discoverable per
profile via `dsh --profile <name> --help`.

### One-shot invocation

`dsh` accepts a task as a command-line argument. The `headless` profile is the
one-shot surface. Its own help states the whole contract:

```
Usage: dsh --profile headless [options] [task...]

Answer one task, print the final assistant message, and exit.

Arguments:
  task        the task text; multiple words are joined by spaces

Options:
  -h, --help  show this help
```

`-h/--help` is its entire option set, so it exposes **no JSON output mode and no
schema argument**; the result is the final assistant message as text.

### Profiles must already exist

A profile name that does not resolve is a hard boot error rather than an
auto-initialization:

```
Error: dsh: profile "tui" does not exist; create it with 'dsh plugin --profile tui add <package>'
```

Profile names are therefore operator-chosen, and upstream's own `--help`
examples (`--profile tui`, `--profile web`) are illustrative rather than a
guaranteed set.

### Resume

`--resume <session>` is an app argument, not a launcher flag. `dsh --help`
documents this positionally: `dsh --profile tui --resume <session>` —
"arguments after the launcher flags reach the app".

## Known caveats

Established only from the installed binary's own help and error output. The
following are **unestablished here** and must not be inferred from this snippet:

- The schema and merge semantics of `--patch` payloads.
- Whether `dsh plugin --profile <name> add` creates a missing profile as a side
  effect of the documented creation instruction.
- Any sandbox or permission behavior; no such flag appears on the launcher.
- `$DSH_HOME`'s default when unset.

TeleClaude's own launch configuration — which profile it boots, and what it
places in a generated patch — is TeleClaude's contract, not dsh's, and lives
with that configuration.

## See Also

- docs/third-party/deepseek-dsh/hooks.md — the dsh-hooks executor's event and decision contract.
