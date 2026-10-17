---
description: 'The runtime-settings layer holds mutable operator toggles (currently only `tts.enabled`) separate from YAML config; patches mutate in-memory state and the TTS manager synchronously, then flush to a JSON state file on a debounced background task.'
visibility: 'public'
---

# Runtime TTS Toggle — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

The runtime-settings layer holds operator toggles distinct from YAML
configuration. YAML files define boot-time settings and require a reload to
take effect; runtime settings let an operator change a live value without
editing YAML. The runtime-settings layer owns that current value and its
best-effort persistence.

In v1 the entire surface is one field: `tts.enabled`. The patch protocol is
namespaced (`tts` section, then field names) so a future section (e.g., `stt`,
`notifications`) can be added without breaking the protocol — but today only
TTS is mutable. An accepted patch updates the current runtime-settings value synchronously
before persistence is scheduled. The TTS system owns consuming this value.

Persistence is JSON, not YAML, and is debounced. Each patch schedules a
background task that sleeps 0.5 seconds and then writes the JSON state file.
If a second patch arrives before the first task wakes, the first task is
cancelled and replaced — only the last patch within a 0.5 s window persists.
Flush failures are caught and logged, never re-raised. The principle is "the
runtime state is the truth; the file is a best-effort cache so we survive a
restart".

On startup, the layer reads the JSON state file (if present) and restores the
stored value into runtime-settings state. A missing or malformed file is
treated as "no prior state" — the runtime-settings value stays at its boot-time
seed.

The YAML `config.tts.enabled` value is the boot-time seed for runtime-settings;
it does not own the live value after startup. If a requested update is refused
by TTS, the runtime-settings value stays unchanged and the refusal is returned
to the caller.

An explicit deprovision request first forces the runtime-settings value off and
persists it before requesting TTS cleanup. If that off-state write fails,
cleanup is not requested. The CLI requires explicit confirmation; the settings
route returns the disabled value on success, 503 when runtime settings are
unavailable, and 500 when persistence or downstream cleanup fails. TTS owns the
dependency lifecycle and cleanup behavior
(`local/projects/teleclaude/design/architecture/tts-system`).

Patch payloads that are empty, malformed, contain unsupported keys, or give
`enabled` a non-boolean value are refused without changing the live state or
scheduling persistence. Guardrail details such as exact parser messages and
serialization format remain outside the operator goal.

## Canonical fields

### Use cases

#### UC-CFG-RUNTIME-1: Operator changes the live TTS setting

```gherkin
Scenario Outline: An accepted change updates the live runtime setting
  Given an operator requests the live TTS setting <choice>
  When configuration accepts the update
  Then the runtime-settings surface reports <choice> immediately
  And the YAML configuration remains unchanged

  Examples:
    | choice |
    | enabled |
    | muted |

Scenario: An invalid toggle request leaves the current setting intact
  Given an operator requests an empty or unsupported TTS patch
  When configuration validates the request
  Then it is refused with a useful validation explanation
  And the runtime-settings value is unchanged
  And no persistence is scheduled

Scenario: A refused enable request leaves the setting off
  Given runtime-settings is off and TTS refuses an enable request
  When configuration handles the refusal
  Then the runtime-settings value remains off
  And the caller receives the refusal
```

#### UC-CFG-RUNTIME-2: Empty patch raises a validation error

#### UC-CFG-RUNTIME-3: Debounced flush coalesces rapid patches

#### UC-CFG-RUNTIME-4: Patch parser rejects unknown top-level keys

#### UC-CFG-RUNTIME-5: Patch parser rejects unknown keys inside the tts block

#### UC-CFG-RUNTIME-6: Patch parser rejects non-boolean enabled

#### UC-CFG-RUNTIME-7: Patch parser rejects non-object top-level payload

#### UC-CFG-RUNTIME-8: Patch parser rejects non-object tts section

#### UC-CFG-RUNTIME-9: Patch parser with tts.enabled absent produces a no-op patch

#### UC-CFG-RUNTIME-10: Operator’s TTS setting is restored on restart

```gherkin
Scenario: A persisted TTS setting is restored on startup
  Given the operator's previously accepted runtime setting was persisted
  When the runtime-settings layer starts
  Then its current value is restored from that persisted setting
  And the YAML boot seed does not overwrite it

Scenario: Startup continues when no usable persisted setting exists
  Given the runtime settings file is missing or malformed
  When the runtime-settings layer starts
  Then its current value remains at the boot-time seed
  And startup continues

Scenario: An unusable enabled value is corrected before exposure
  Given the persisted runtime setting is enabled but TTS reports that its dependencies are unavailable
  When startup reconciles runtime settings
  Then the runtime-settings value is forced off before settings are reported
  And the off value is persisted
```

#### UC-CFG-RUNTIME-11: Startup with missing state file leaves seeded state intact

#### UC-CFG-RUNTIME-12: Startup with malformed JSON is logged and swallowed

#### UC-CFG-RUNTIME-13: Persistence with no running event loop is a no-op

#### UC-CFG-RUNTIME-14: Flush failure is logged, not raised

#### UC-CFG-RUNTIME-15: Flush writes the full state shape, not a diff

#### UC-CFG-RUNTIME-16: Operator’s live TTS setting survives a YAML reload

```gherkin
Given an operator has set the runtime TTS value to muted while YAML enables it
When a TTS-section configuration reload occurs
Then the runtime-settings value remains muted
```

#### UC-CFG-RUNTIME-17: Enabling TTS provisions the optional deps before the flag flips

#### UC-CFG-RUNTIME-18: Enabling on an unsupported platform or a failed install fails closed

#### UC-CFG-RUNTIME-19: Muting never provisions or uninstalls

#### UC-CFG-RUNTIME-20: Startup with a replayed enabled=True but unprovisioned deps fails closed

#### UC-CFG-RUNTIME-21: Operator requests TTS deprovision

```gherkin
Scenario: A confirmed deprovision request reaches TTS after configuration stores off
  Given an operator explicitly confirms TTS deprovision
  When configuration accepts the request
  Then the runtime-settings value is off and persisted before cleanup is requested
  And the caller receives the operation result

Scenario: An unconfirmed deprovision request does not reach TTS
  Given the operator has not explicitly confirmed deprovision
  When the CLI request is made
  Then the CLI asks for confirmation
  And no cleanup request is sent

Scenario: Persistence failure prevents a cleanup request
  Given persisting the forced-off runtime-settings value fails
  When the operator confirms deprovision
  Then cleanup is not requested
  And the in-memory runtime-settings value remains off
  And the failure is reported to the caller

Scenario: TTS cleanup failure is returned with runtime settings still off
  Given the runtime-settings value is off and persisted
  And TTS cleanup fails
  When the operator confirms deprovision
  Then the route reports the downstream failure
  And the runtime-settings value remains off

Scenario: An unavailable runtime refuses deprovision
  Given no runtime-settings layer is available to the settings route
  When the operator confirms deprovision
  Then the route reports that runtime settings are unavailable
  And no cleanup request is sent
```

#### UC-CFG-RUNTIME-22: A failed off-state persist blocks dependency removal

#### UC-CFG-RUNTIME-23: Deprovision still removes dependencies when TTS is already disabled

#### UC-CFG-RUNTIME-24: The deprovision route returns the disabled state on success

#### UC-CFG-RUNTIME-25: The deprovision route maps a dependency-removal failure to 500

#### UC-CFG-RUNTIME-26: The deprovision route maps an off-state persist failure to 500

#### UC-CFG-RUNTIME-27: The deprovision route rejects an unwired runtime-settings layer

#### UC-CFG-RUNTIME-28: The CLI deprovision verb guards without an explicit confirmation flag

#### UC-CFG-RUNTIME-29: The CLI deprovision verb calls the daemon once when confirmed

#### UC-CFG-RUNTIME-30: The CLI deprovision verb surfaces a daemon API error

#### UC-CFG-RUNTIME-31: Top-level CLI dispatch routes tts to the config tts handler

#### UC-CFG-RUNTIME-32: Dependency removal runs the resolver-inverse command from the repo root

#### UC-CFG-RUNTIME-33: A failed removal command fails closed

### Cross-context references

- **TTS consumption and dependencies.** Configuration owns the accepted live
  `tts.enabled` value and operator request. The TTS system owns how it consumes
  that value and the optional dependency lifecycle
  (`local/projects/teleclaude/design/architecture/tts-system`). The target
  model coordinates these contexts through an effective-configuration-updated
  event.
- **Distinct from the YAML overlays.** The `tts` block in `teleclaude.yml`
  (and in machine `config.yml`) defines boot-time TTS shape — voices,
  services, event mappings, the initial `enabled` value seeded into the
  TTS manager. The runtime-settings layer does not mutate those YAML
  files. The JSON state file is a separate persistence surface.
- **No domain event today.** A patch does not emit
  the effective-configuration-updated event or any other event. Consumers other than the
  TTS context learn about a toggle only by reading the TTS context's
  enabled flag directly.

## Allowed values

- Top-level keys in a parsed patch: `{"tts"}` only.
- Keys inside the `tts` object: `{"enabled"}` only.
- Type of `tts.enabled`: `bool` only — no string-to-bool coercion.

## Known caveats

- **One-field surface.** The mutable runtime layer is `tts.enabled` and
  nothing else. Any other operator toggle that needs immediate effect in v1
  has to be plumbed through a different mechanism today.
- **Best-effort persistence.** A crash within the 0.5 s debounce window
  loses the most recent toggle. The in-memory and TTS-manager state stay
  consistent inside the process; the disk cache lags.
- **No fsync on flush.** The flush writes the state file without a
  kernel-level sync and without an atomic-replace pattern. A power loss
  mid-write can truncate the JSON file. On the next startup, the state-file
  read detects malformed JSON, logs the failure, and falls back to the
  TTS manager's boot-time value.
- **Loop-absence is silent.** If a patch runs in a sync context with no
  background event loop, the mutation is applied in memory but persistence
  is skipped without warning. Operator-facing code is expected to run under
  the runtime's event loop; a CLI that mutated settings outside the runtime
  would lose its writes until the next loop-bound patch.
- **Patches replace, never merge nested partials.** The patch parser accepts
  only the `enabled` field today, so the surface is too narrow for a true
  merge problem to surface. When the surface grows, the patch protocol
  will need to clarify "set explicitly" vs. "leave unchanged" semantics
  beyond the current `None` sentinel.
- **The returned settings state reference is live.** A consumer that holds
  the reference returned by the current-state reader observes future
  mutations from subsequent patches automatically (and could in principle
  mutate the state directly, bypassing the patch's TTS manager dual-write).
  v1 relies on callers to treat the returned state as read-only.
- **No teardown for the pending flush task.** If the owning event loop shuts
  down with a pending flush scheduled, the task is cancelled by the loop's
  shutdown logic; v1 does not expose an explicit shutdown hook to await the
  final flush deterministically.
