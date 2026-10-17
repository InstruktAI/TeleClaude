---
description: 'The runtime-settings layer holds mutable operator toggles (currently only `tts.enabled`) separate from YAML config; patches mutate in-memory state and the TTS manager synchronously, then flush to a JSON state file on a debounced background task.'
visibility: 'public'
---

# Runtime TTS Toggle — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

The runtime-settings layer holds runtime-mutable operator toggles distinct
from the YAML configuration surface. YAML files define the boot-time shape of
the system and require a reload to take effect; the runtime-settings layer
exists for the narrow case where an operator flips a switch and expects the
next event to honour the new value immediately, with persistence as a
best-effort side effect rather than the authoritative path.

In v1 the entire surface is one field: `tts.enabled`. The patch protocol is
namespaced (`tts` section, then field names) so a future section (e.g., `stt`,
`notifications`) can be added without breaking the protocol — but today only
TTS is mutable. The toggle is dual-written on every patch: the in-memory
settings state AND the live TTS manager's enabled flag are updated
synchronously before the persistence task is scheduled. A consumer reading the
TTS manager's enabled flag after a patch is guaranteed to see the new value.

Persistence is JSON, not YAML, and is debounced. Each patch schedules a
background task that sleeps 0.5 seconds and then writes the JSON state file.
If a second patch arrives before the first task wakes, the first task is
cancelled and replaced — only the last patch within a 0.5 s window persists.
Flush failures are caught and logged, never re-raised. The principle is "the
runtime state is the truth; the file is a best-effort cache so we survive a
restart".

On startup, the layer reads the JSON state file (if present) and replays the
stored values back into both the in-memory settings state and the TTS manager.
A missing or malformed file is treated as "no prior state" — the layer falls
back to whatever the TTS manager was already initialised with.

The YAML `config.tts.enabled` value seeds the boot-time TTS choice; runtime
settings owns the live choice. Provisioned state is determined by whether the
required dependencies for a configured, supported TTS service are available,
not by the YAML flag alone. Enabling TTS is accepted only when those dependencies
are available; failed provisioning leaves TTS disabled. Muting never provisions
or removes dependencies. If startup restores an enabled value but the
dependencies are unavailable, TTS is disabled and the off state is persisted
without installing dependencies at startup.

Explicit deprovision is separate from muting: TTS is forced off and that state
is persisted before TTS-exclusive dependencies are removed; dependencies shared
with other features remain. If the off state cannot be persisted, removal does
not start. The operation still removes TTS-exclusive dependencies if TTS was
already off. The CLI requires explicit confirmation before calling the daemon;
the settings route returns the disabled state on success, reports unavailable
runtime settings as unavailable, and reports persistence or removal failures
without presenting them as success.

Patch payloads that are empty, malformed, contain unsupported keys, or give
`enabled` a non-boolean value are refused without changing the live state or
scheduling persistence. Guardrail details such as exact parser messages and
serialization format remain outside the operator goal.

## Canonical fields

### Use cases

#### UC-CFG-RUNTIME-1: Operator changes the live TTS choice

```gherkin
Scenario Outline: An accepted TTS choice takes effect immediately
  Given an operator changes the live TTS choice to <choice>
  When the change is accepted
  Then the next TTS event follows <choice> without a YAML reload

  Examples:
    | choice |
    | enabled |
    | muted |

Scenario: An invalid toggle request leaves the current choice intact
  Given an operator requests an empty or unsupported TTS patch
  When the request is validated
  Then it is refused with a useful validation explanation
  And the live choice is unchanged
  And no persistence is scheduled

Scenario: TTS stays off when it cannot be enabled safely
  Given an operator requests TTS and no configured service is supported or provisioning fails
  When the request is applied
  Then TTS remains disabled
  And no TTS voice is emitted
  And the operator receives a clear failure

Scenario: Muting does not change installed dependencies
  Given TTS is enabled and its dependencies are installed
  When the operator mutes TTS
  Then the live choice changes to muted immediately
  And no dependency is installed or removed
```

#### UC-CFG-RUNTIME-2: Empty patch raises a validation error

#### UC-CFG-RUNTIME-3: Debounced flush coalesces rapid patches

#### UC-CFG-RUNTIME-4: Patch parser rejects unknown top-level keys

#### UC-CFG-RUNTIME-5: Patch parser rejects unknown keys inside the tts block

#### UC-CFG-RUNTIME-6: Patch parser rejects non-boolean enabled

#### UC-CFG-RUNTIME-7: Patch parser rejects non-object top-level payload

#### UC-CFG-RUNTIME-8: Patch parser rejects non-object tts section

#### UC-CFG-RUNTIME-9: Patch parser with tts.enabled absent produces a no-op patch

#### UC-CFG-RUNTIME-10: Operator’s TTS choice is restored on restart

```gherkin
Scenario: A persisted TTS choice is restored on startup
  Given the operator's previously accepted TTS choice was persisted
  When the runtime starts
  Then that choice is restored for subsequent TTS events
  And the YAML boot default does not overwrite it

Scenario: Startup continues when no usable persisted choice exists
  Given the runtime settings file is missing or malformed
  When the runtime starts
  Then the TTS manager's initialized boot choice remains in effect
  And startup continues

Scenario: An enabled choice is disabled when its dependencies are unavailable
  Given the persisted choice is enabled but required TTS dependencies are unavailable
  When the runtime reconciles its startup state
  Then TTS is forced off before settings are reported
  And the off choice is persisted without installing dependencies at startup
```

#### UC-CFG-RUNTIME-11: Startup with missing state file leaves seeded state intact

#### UC-CFG-RUNTIME-12: Startup with malformed JSON is logged and swallowed

#### UC-CFG-RUNTIME-13: Persistence with no running event loop is a no-op

#### UC-CFG-RUNTIME-14: Flush failure is logged, not raised

#### UC-CFG-RUNTIME-15: Flush writes the full state shape, not a diff

#### UC-CFG-RUNTIME-16: Operator’s live TTS choice survives a YAML reload

```gherkin
Given an operator has chosen to mute TTS at runtime while YAML enables it
When the TTS configuration reloads other settings such as voices or services
Then the operator's live mute remains in effect
And no session-start voice is spoken while TTS is muted
```

#### UC-CFG-RUNTIME-17: Enabling TTS provisions the optional deps before the flag flips

#### UC-CFG-RUNTIME-18: Enabling on an unsupported platform or a failed install fails closed

#### UC-CFG-RUNTIME-19: Muting never provisions or uninstalls

#### UC-CFG-RUNTIME-20: Startup with a replayed enabled=True but unprovisioned deps fails closed

#### UC-CFG-RUNTIME-21: Operator removes TTS-exclusive dependencies

```gherkin
Scenario: Confirmed deprovision removes only TTS-exclusive dependencies
  Given an operator explicitly confirms TTS deprovision
  When deprovision succeeds
  Then TTS is off and that state was persisted before dependency removal
  And only TTS-exclusive dependencies are removed
  And dependencies shared with other features remain installed
  And the returned settings state reports TTS off

Scenario: Deprovision still cleans up when TTS is already muted
  Given TTS is already off and TTS-exclusive dependencies remain installed
  When the operator confirms deprovision
  Then the exclusive dependencies are removed
  And shared dependencies remain installed

Scenario: An unconfirmed deprovision request does not call the service
  Given the operator has not explicitly confirmed deprovision
  When the CLI request is made
  Then the CLI asks for confirmation
  And no deprovision request is sent

Scenario: Persistence failure blocks deprovision
  Given persisting the forced-off TTS state fails
  When the operator confirms deprovision
  Then dependency removal does not begin
  And the failure is reported to the operator

Scenario: Removal failure does not present deprovision as successful
  Given the TTS state is off and persisting it succeeded
  And removing the exclusive dependencies fails or the runtime service is unavailable
  When the operator confirms deprovision
  Then the failure is reported to the operator
  And no success result is returned
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

- **Cross-context write into the TTS context.** The runtime-settings
  patcher reaches into a different bounded context — TTS — and mutates
  its `enabled` flag directly. The relationship is "config owns the
  toggle; TTS owns the consumption". The current coupling is a direct
  in-process write held together by convention; the same coordination
  would flow through an effective-configuration-updated event consumed by the
  TTS context in the target model.
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
