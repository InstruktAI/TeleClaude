---
description: 'The runtime-settings layer holds mutable operator toggles (currently only `tts.enabled`) separate from YAML config; patches mutate in-memory state and the TTS manager synchronously, then flush to a JSON state file on a debounced background task.'
visibility: 'public'
---

# Runtime TTS Toggle — Spec

## Required reads

- @docs/project/spec/domain/config.md

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

## Canonical fields

### Use cases

#### UC-CFG-RUNTIME-1: patch flips TTS in-memory and on the TTS manager

```
Given the runtime-settings layer has tts.enabled = False and the TTS manager's enabled flag is False
And an incoming patch payload sets tts.enabled = True
When the patch is applied
Then the in-memory tts.enabled is set to True synchronously
And the TTS manager's enabled flag is set to True synchronously
And a success log entry "Runtime tts.enabled -> True" is emitted
And a debounced persist to disk is scheduled
And the patch returns the updated settings state
```

#### UC-CFG-RUNTIME-2: Empty patch raises a validation error

```
Given an incoming patch payload where no mutable field is set
  (tts section absent, or tts.enabled absent)
When the patch is applied
Then no mutation occurs
And a validation error "No mutable settings in patch" is raised
And no flush is scheduled
```

#### UC-CFG-RUNTIME-3: Debounced flush coalesces rapid patches

```
Given two patch calls arrive within 0.5 seconds while the service is running
When the first patch schedules a debounced flush
And the second patch arrives before the first flush fires
Then the pending flush is cancelled
And a fresh flush is scheduled 0.5 s from the second call
And only the most recent state is written to disk when the flush fires
```

#### UC-CFG-RUNTIME-4: Patch parser rejects unknown top-level keys

```
Given a raw JSON body {"tts": {"enabled": true}, "weather": "sunny"}
When the patch parser validates the payload
Then the unknown top-level key "weather" is identified (only "tts" is allowed)
And a validation error "Unknown settings keys: ['weather']" is raised
And no patch payload is produced
```

#### UC-CFG-RUNTIME-5: Patch parser rejects unknown keys inside the tts block

```
Given a raw JSON body {"tts": {"enabled": true, "volume": 0.8}}
When the patch parser validates the payload
Then the top-level key check passes
And the unknown tts key "volume" is identified (only "enabled" is allowed)
And a validation error "Unknown tts keys: ['volume']" is raised
```

#### UC-CFG-RUNTIME-6: Patch parser rejects non-boolean enabled

```
Given a raw JSON body {"tts": {"enabled": "true"}}
When the patch parser validates the payload
Then the value "true" is a string, not a bool
And a validation error "tts.enabled must be a boolean" is raised
And no implicit coercion of "true" -> True is performed
```

#### UC-CFG-RUNTIME-7: Patch parser rejects non-object top-level payload

```
Given a raw JSON body that parsed into a list, string, or None
When the patch parser validates the payload
Then the top-level shape is not a JSON object
And a validation error "Expected JSON object" is raised
```

#### UC-CFG-RUNTIME-8: Patch parser rejects non-object tts section

```
Given a raw JSON body {"tts": true}
When the patch parser validates the payload
Then the top-level key check passes
And the tts value is not a JSON object
And a validation error "tts must be an object" is raised
```

#### UC-CFG-RUNTIME-9: Patch parser with tts.enabled absent produces a no-op patch

```
Given a raw JSON body {"tts": {}}
When the patch parser validates the payload
Then no unknown keys are found in the tts block
And "enabled" is absent, so the tts enabled delta is None (no-op)
And a patch payload with no active changes is returned
And a subsequent apply of this payload raises "No mutable settings in patch"
```

#### UC-CFG-RUNTIME-10: Startup replays persisted tts.enabled into the TTS manager

```
Given the JSON state file at the configured state path exists and contains {"tts": {"enabled": true}}
When the runtime-settings layer starts up
Then the layer stores the state path and takes the TTS manager reference
And initialises in-memory state seeded from the TTS manager's current enabled flag
And reads the persisted JSON state file
And replays the stored value: in-memory tts.enabled = True, TTS manager enabled = True
```

#### UC-CFG-RUNTIME-11: Startup with missing state file leaves seeded state intact

```
Given the configured state path does NOT exist on disk
When the runtime-settings layer starts up
Then the state-file read returns nothing
And startup proceeds without replaying any persisted state
And the in-memory state stays seeded from the TTS manager's enabled flag at startup time
```

#### UC-CFG-RUNTIME-12: Startup with malformed JSON is logged and swallowed

```
Given the state path exists but contains invalid JSON (or a non-object JSON value)
When the runtime-settings layer starts up
Then the JSON parse fails
And the failure is logged: "Failed to read runtime settings from {settings_path}"
And the state-file read returns nothing
And startup succeeds — the in-memory state stays seeded from the TTS manager's boot-time value
```

#### UC-CFG-RUNTIME-13: Persistence with no running event loop is a no-op

```
Given the runtime-settings layer is in a context with no running event loop when a flush is due
When the layer attempts to schedule a debounced persist
Then no background task is created (scheduling is skipped silently)
And the in-memory mutation from the prior patch call still stands
And the disk file is NOT updated for that call (will be updated by the next patch that runs under a live event loop)
```

#### UC-CFG-RUNTIME-14: Flush failure is logged, not raised

```
Given a debounced flush fires
And the write to the state path raises (disk full, permission denied, etc.)
When the exception propagates inside the flush
Then the failure is logged: "Failed to flush runtime settings to disk"
And the exception is swallowed
And the in-memory state remains correct; only the on-disk cache is stale
```

#### UC-CFG-RUNTIME-15: Flush writes the full state shape, not a diff

```
Given a successful debounced flush
When the flush runs
Then the state file's parent directory is created if absent
And the current state is serialised as JSON: {"tts": {"enabled": <current bool>}}
And the JSON is written to the state path (utf-8, pretty-printed, keys sorted)
And a success log entry is emitted
```

<!-- planned:tts-reload-no-clobber -->

#### UC-CFG-RUNTIME-16: A tts-section config reload preserves the runtime-owned enabled flag

```
Given the runtime-settings layer has set tts.enabled = False on the TTS manager
And the YAML config has tts.enabled = True
When a tts-section config reload fires because a tts field changed (a voice, a service, or an event mapping)
Then the TTS manager refreshes its config-derived state from YAML (services, voices, events, service priority)
And the TTS manager's live enabled flag stays False
And no session-start voice is spoken while the runtime layer holds TTS muted
```

<!-- /planned:tts-reload-no-clobber -->

### Cross-context references

- **Cross-context write into the TTS context.** The runtime-settings
  patcher reaches into a different bounded context — TTS — and mutates
  its `enabled` flag directly. The relationship is "config owns the
  toggle; TTS owns the consumption". The current coupling is a direct
  in-process write held together by convention; the same coordination
  would flow through a `config.effective.updated` event consumed by the
  TTS context in the target model.
- **Distinct from the YAML overlays.** The `tts` block in `teleclaude.yml`
  (and in machine `config.yml`) defines boot-time TTS shape — voices,
  services, event mappings, the initial `enabled` value seeded into the
  TTS manager. The runtime-settings layer does not mutate those YAML
  files. The JSON state file is a separate persistence surface.
- **No domain event today.** A patch does not emit
  `config.effective.updated` or any other event. Consumers other than the
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
