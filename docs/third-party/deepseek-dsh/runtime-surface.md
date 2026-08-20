---
description: DeepSeek Harness (dsh) CLI surface — profile booting, the one-shot headless invocation, patch overlays, and session resume.
---

# DeepSeek Harness (dsh) — Runtime Surface

## What it is

`dsh` boots a **profile**: an ordered stack of plugin-bundle patch layers under
the operator's own overrides. The launcher owns a small flag set; everything
after those flags reaches the booted profile's app.

Observed against dsh `0.1.0-rc.7`.

## Canonical fields

### Launcher flags

| Flag                    | Meaning                                                              |
| ----------------------- | -------------------------------------------------------------------- |
| `--profile <name>`      | The profile under `$DSH_HOME/profiles` to boot                       |
| `--patch <path>`        | Extra patch-list overlay applied after the profile layer; repeatable |
| `--dump-config`         | Print the composed profile tree and exit                             |
| `--dump-default-config` | Print the profile tree without its user layer or `--patch` overlays  |
| `-V, --version`         | Print the version                                                    |

Sub-commands: `web` (alias of `--profile web`) and
`plugin --profile <name> <pnpm args...>` (plugin management, forwarded to pnpm
in the profile directory).

### One-shot invocation

`dsh` takes a task as a command-line argument. The `headless` profile is the
one-shot surface:

```
dsh --profile headless "run the tests"
```

Its own help states the contract: **"Answer one task, print the final assistant
message, and exit."** Multiple words are joined by spaces. The headless app
declares no other flags — `-h, --help` is its entire option set, so it offers no
JSON output mode and no schema argument; its output is the final assistant
message as text.

### Profiles are operator-created, and the launch profile is not named `tui`

Profiles exist only where an operator created them; the launcher errors rather
than initializing one:

```
Error: dsh: profile "tui" does not exist; create it with 'dsh plugin --profile tui add <package>'
```

The profiles present on a TeleClaude-provisioned machine are `dsh-tui`,
`headless`, and `web`. **`dsh-tui` is the interactive launch profile** — the
name `tui` does not resolve. `$DSH_HOME` is normally unset and defaults to
`~/.dsh`.

### Model parameters travel in a patch, not a flag

There is no model flag. Model and reasoning-effort are applied per launch
through a generated `--patch` overlay with replace semantics: an
`agent-default-model` entry must carry `provider` and `model` together, because
setting `model` alone drops the provider and fails boot. The same mechanism
carries the restricted-mode sandbox override.

### Resume

`--resume <session>` is an app argument, not a launcher flag — it follows the
launcher flags and reaches the profile's app:

```
dsh --profile dsh-tui --resume <session>
```

## Known caveats

- A profile name that does not exist is a hard boot error, so a launcher must
  never guess one. `dsh plugin --profile <name> add <package>` silently
  initializes a missing profile, which is why installer code guards on
  existence before calling it.
- The headless profile prints the final assistant message only. Any structured
  output has to be produced by the model into that text, not requested through a
  CLI flag.

## See Also

- docs/third-party/deepseek-dsh/hooks.md — the dsh-hooks executor's event and decision contract.
