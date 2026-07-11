---
description: Ownership and update boundaries between the LM Studio desktop app, standalone llmster daemon, lms CLI, and inference runtimes.
---

# LM Studio, llmster, and lms

## Components

- **LM Studio** is the desktop application. It can run its model server in the
  background, but its lifecycle remains owned by the desktop installation.
- **llmster** is the standalone, headless daemon. It packages the serving core
  independently of the desktop app and is installed on macOS or Linux through
  LM Studio's official shell installer.
- **`lms`** is the shared CLI for both runtimes. It is bundled with either LM
  Studio or llmster, so the presence of `lms` alone does not identify which
  runtime owns the installation.
- **Inference runtimes** are separately managed execution engines. Updating an
  inference runtime does not update llmster or the desktop app.

## TeleClaude installation ownership

TeleClaude treats the desktop app and llmster as separate installations:

- The optional LM Studio desktop app is installed through the Homebrew cask and
  remains Homebrew-governed.
- The standalone llmster daemon is installed separately through
  `https://lmstudio.ai/install.sh`, even when the desktop app is present. This
  gives TeleClaude a daemon-shaped runtime whose lifecycle does not depend on
  opening or updating the GUI application.

Consequently, a Homebrew update of LM Studio does not satisfy TeleClaude's
llmster update responsibility. Ownership must be established from the active
installation and daemon, not inferred from the existence of the `lms` command.

## Update lifecycle

### Ownership probe

`lms daemon status --json` reports the active runtime's state and ownership in
one machine-readable shape (verified against `lms` bundled with
LM Studio v0.4.15):

```json
{ "status": "running", "pid": 745, "isDaemon": false }
```

- `isDaemon: true` — the standalone llmster daemon owns the runtime.
- `isDaemon: false` — the LM Studio desktop app owns it; standalone llmster is
  not governing this host even though `lms` resolves on PATH.
- `status` reports whether the runtime is currently running.

This probe — not the presence of the `lms` executable — is how standalone
llmster ownership is established.

### Update commands

Update standalone llmster through its own CLI lifecycle:

```bash
lms daemon down
lms daemon update
lms daemon up
```

`lms daemon update` installs the latest stable llmster release; `--beta` selects
the beta channel. The daemon must be stopped before updating and started again
afterward.

Do not substitute `lms runtime update`: that command updates an installed
inference runtime, not llmster itself.

## Sources

- [Run LM Studio as a service (headless)](https://lmstudio.ai/docs/developer/core/headless)
- [LM Studio, llmster, and lms](https://lmstudio.ai/docs/app/basics/lmstudio-vs-llmster-vs-lms)
- [Update llmster](https://lmstudio.ai/docs/cli/daemon/daemon-update)
- [Manage inference runtimes](https://lmstudio.ai/docs/cli/runtime/runtime)
