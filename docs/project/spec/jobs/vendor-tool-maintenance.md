---
description: Installation and scheduled updates for TeleClaude's external command-line tools and local runtime dependencies.
delivered_by:
  - scheduled-vendor-tool-maintenance
---

# Vendor Tool Maintenance — Spec

## What it is

TeleClaude provides one shared vendor-tool manager for installation-time dependency
checks and unattended scheduled updates. `make install` uses its ensure mode to
preserve a low-friction setup flow, while the jobs runner invokes its update mode
daily for tools whose vendor installation method lies outside Homebrew.

The manager honors the installed agent configuration. It installs or updates an
agent CLI only when that agent is enabled, and reports each attempted tool
independently so one vendor failure does not hide the remaining results.

## Canonical fields

- **Ensure mode:** Installs missing enabled agent CLIs, standalone llmster, and
  required or selected local dependencies. Existing tools are left unchanged;
  scheduled update mode owns periodic upgrades.
- **Update mode:** Updates enabled Claude, Codex, and Antigravity CLIs through
  their vendor-supported commands, and updates standalone llmster through its
  supported installer. It never installs or upgrades Homebrew formulae or casks.
- **Homebrew dependencies:** `make install` may install a missing formula or cask
  required by the selected configuration. Subsequent Homebrew updates remain the
  host owner's responsibility. The README may point to the InstruktAI dotfiles
  updater as an optional example, but TeleClaude never depends on or invokes it.
- **LM Studio and llmster:** A user selecting the local llmster runtime receives
  both the LM Studio GUI cask prerequisite and the standalone llmster command.
  TeleClaude governs standalone llmster updates. When llmster is running, update
  mode stops it, updates it, and starts it again; when it is stopped, update mode
  preserves that state.
- **Handy:** Remains an optional installation choice and is documented as the
  offered desktop dictation tool. It is distinct from adapter voice-message
  transcription, which uses the configured Parakeet or Whisper implementation.
- **Redis:** A configured remote Redis URL suppresses local Redis setup. Without
  one, installation retains the optional local Redis install and service setup
  for a single-computer deployment.
- **Other native dependencies:** `ffmpeg` remains available to satisfy lower-level
  project dependencies. `socat` is not installed because TeleClaude has no runtime
  consumer for it.
- **MCP setup:** Installation does not invoke the obsolete MCP setup stub that only
  reports that configuration migrated to telec workflows. Active agent CLI
  configuration remains in place.
- **Schedule:** A system script job runs update mode daily at 07:00 local time,
  after the host's expected Homebrew maintenance window and before normal use.
- **Execution safety:** Update mode is non-interactive, protected against
  concurrent runs, applies a finite timeout per tool, records per-tool outcomes,
  and exits unsuccessfully when any selected update fails.
- **Documentation:** The README states which dependencies TeleClaude installs,
  which updater owns each dependency class, and how Handy, Redis, LM Studio, and
  llmster relate to optional functionality.

## Allowed values

The manager accepts exactly `ensure` and `update` as operating modes. The set of
agent CLI operations is derived from the validated installed-agent configuration;
it is not maintained as a second user-facing configuration surface.

## Known caveats

- Vendor installers and update commands are external contracts. A failed vendor
  command is isolated to that tool and surfaced in the aggregate job result.
- Homebrew availability is required only when installation needs to add a missing
  Homebrew-governed dependency. Scheduled update mode does not require Homebrew.
