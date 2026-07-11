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
  TeleClaude governs standalone llmster updates. Standalone ownership is
  established through the daemon status probe, never from the presence of the
  shared `lms` command; a runtime owned by the desktop app is not updated by
  TeleClaude. When llmster is running, update mode stops it, updates it, and
  starts it again; when it is stopped, update mode preserves that state.
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
- **Subprocess environment:** Vendor install and update processes receive a
  minimal allowlisted environment — baseline process variables and any
  vendor-required values only. TeleClaude adapter and service credentials are
  never passed to vendor tooling.
- **Documentation:** The README states which dependencies TeleClaude installs,
  which updater owns each dependency class, and how Handy, Redis, LM Studio, and
  llmster relate to optional functionality.

### Use cases

#### UC-VTM1: Ensure installs a missing enabled agent CLI

```
Given an agent CLI that is enabled in the installed-agent configuration
And its command is missing from the host
When the manager runs in ensure mode
Then that agent CLI's vendor installer is invoked
And the run's per-tool outcomes record the installation result
```

#### UC-VTM2: Ensure skips a disabled agent CLI

```
Given an agent CLI that is disabled in the installed-agent configuration
And its command is missing from the host
When the manager runs in ensure mode
Then no vendor command is invoked for that agent CLI
And its absence does not fail the run
```

#### UC-VTM3: Ensure leaves an already-installed tool unchanged

```
Given an enabled agent CLI whose command is already present on the host
When the manager runs in ensure mode
Then no install or update command is invoked for that tool
And the tool's outcome records that it was left unchanged
```

#### UC-VTM4: Update touches vendor tools only, never Homebrew

```
Given enabled agent CLIs and standalone llmster are installed
When the manager runs in update mode
Then each enabled agent CLI's vendor update command is invoked
And llmster is updated through its supported installer
And no Homebrew command is invoked
```

#### UC-VTM5: One vendor failure isolates and fails the aggregate

```
Given multiple enabled tools are selected for update
And one tool's vendor command fails
When the manager runs in update mode
Then the remaining tools are still attempted
And the failed tool's outcome records the failure
And the aggregate result is unsuccessful
```

#### UC-VTM6: Concurrent runs are excluded

```
Given a vendor-tool run holds the concurrency lock
When a second run starts in either mode
Then the second run performs no vendor operations
And its result reports the concurrent-run refusal
```

#### UC-VTM7: A hung vendor command is bounded by the per-tool timeout

```
Given a tool whose vendor command never completes
When the manager runs in update mode
Then that tool's execution is stopped at the per-tool timeout
And the tool's outcome records a timeout failure
And the remaining tools are still attempted
```

#### UC-VTM8: llmster running state is restored around its update

```
Given llmster is running
When the manager updates llmster
Then llmster is stopped before the update
And llmster is started again after the update
```

#### UC-VTM9: llmster stopped state is preserved

```
Given llmster is not running
When the manager updates llmster
Then llmster is updated without being started
```

#### UC-VTM10: Vendor processes receive a minimal allowlisted environment

```
Given the process environment carries TeleClaude service credentials
When the manager invokes any vendor command in either mode
Then the vendor process environment contains only allowlisted variables
And no TeleClaude credential is present in it
```

#### UC-VTM11: A selected missing native dependency is installed via the platform package manager

```
Given a selected native dependency whose command is missing from the host
When the manager runs in ensure mode
Then the platform's package manager install command is invoked for it
And the run's per-tool outcomes record the installation result
```

#### UC-VTM12: A present native dependency is never upgraded

```
Given a selected native dependency whose command is already present on the host
When the manager runs in ensure mode
Then no package-manager command is invoked for it
And the tool's outcome records that it was left unchanged
```

#### UC-VTM13: A remote Redis URL suppresses local Redis setup

```
Given a remote Redis URL is configured
And the Redis dependency is selected
When the manager runs in ensure mode
Then no Redis install or service command is invoked
And the Redis outcome records the remote-configuration suppression
```

#### UC-VTM14: Selecting llmster carries the LM Studio prerequisite

```
Given llmster is selected
And neither LM Studio nor llmster is present on the host
When the manager runs in ensure mode
Then the LM Studio prerequisite is installed before the llmster installer runs
```

#### UC-VTM15: Update mode rejects a dependency selection

```
Given an update-mode invocation that carries a dependency selection
When the manager boundary validates the invocation
Then the invocation is rejected with an error before any vendor operation
```

#### UC-VTM16: A desktop-owned lms runtime is not updated as llmster

```
Given the lms command is present
And the daemon ownership probe reports the runtime is not standalone-owned
When the manager runs in update mode
Then no llmster update command is invoked
And the llmster outcome records that no standalone installation owns the runtime
```

## Allowed values

The manager accepts exactly `ensure` and `update` as operating modes. The set of
agent CLI operations is derived from the validated installed-agent configuration;
it is not maintained as a second user-facing configuration surface.

## Known caveats

- Vendor installers and update commands are external contracts. A failed vendor
  command is isolated to that tool and surfaced in the aggregate job result.
- Homebrew availability is required only when installation needs to add a missing
  Homebrew-governed dependency. Scheduled update mode does not require Homebrew.
