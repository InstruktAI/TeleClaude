---
id: project/spec/feature/config/runtime-tts-toggle
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: RuntimeSettings holds the mutable runtime-settings layer (currently only tts.enabled) separate from YAML config; patches mutate in-memory state and the TTS manager synchronously, then flush to a JSON state file on a debounced asyncio task.
---

# Runtime TTS Toggle — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

`RuntimeSettings` is a small in-memory layer that holds runtime-mutable
operator toggles distinct from the YAML configuration surface. YAML files
define the boot-time shape of the system and require a reload to take
effect; `RuntimeSettings` exists for the narrow case where an operator
flips a switch and expects the next event to honour the new value
immediately, with persistence as a best-effort side effect rather than the
authoritative path.

In v1 the entire surface is one field: `tts.enabled`. The class is
structured to grow — `SettingsState`, `SettingsPatch`, `parse_patch` all
take a nested-namespace shape so a future section (e.g., `stt`,
`notifications`) can be added without breaking the patch protocol — but
today only TTS is mutable. The toggle is dual-written on every patch:
the in-memory `SettingsState.tts.enabled` AND the live `TTSManager.enabled`
attribute (which is a different bounded context's mutable surface) are
updated synchronously inside `patch()`, before the persistence task is
scheduled. A consumer reading `tts_manager.enabled` after `patch()`
returns is guaranteed to see the new value.

Persistence is JSON, not YAML, and is debounced. Each `patch()` call
schedules an asyncio task that sleeps `FLUSH_DELAY_S` (0.5 seconds) and
then writes the JSON state file. If a second `patch()` arrives before the
first task wakes, the first task is cancelled and replaced — only the last
patch within a 0.5 s window persists. The flush is fire-and-forget on
behalf of the caller: failures are caught and logged via
`logger.exception`, never re-raised. The principle is "the runtime state
is the truth; the file is a best-effort cache so we survive a restart".

On startup, `__init__` calls `_load_from_disk` to read the JSON file (if
present) and replay the stored values back into both `SettingsState` and
the `TTSManager`. A missing or malformed file is treated as "no prior
state" — the constructor falls back to whatever the `TTSManager` was
already initialised with.

## Canonical fields

### Use cases

#### UC-CFG-RUNTIME-1: patch flips TTS in-memory and on the TTS manager

```
Given a RuntimeSettings instance with state.tts.enabled = False and tts_manager.enabled = False
And a SettingsPatch with tts = TTSSettingsPatch(enabled=True)
When runtime_settings.patch(updates) is called
Then state.tts.enabled is set to True synchronously
And tts_manager.enabled is set to True synchronously
And logger.info logs "Runtime tts.enabled -> True"
And _schedule_flush is called
And patch returns the updated SettingsState
```

#### UC-CFG-RUNTIME-2: Empty patch raises ValueError

```
Given a RuntimeSettings instance
And a SettingsPatch with tts=None (or tts=TTSSettingsPatch(enabled=None))
When patch(updates) is called
Then no mutation occurs
And ValueError("No mutable settings in patch") is raised
And _schedule_flush is NOT called
```

#### UC-CFG-RUNTIME-3: Debounced flush coalesces rapid patches

```
Given two patch(updates) calls arrive within 0.5 seconds inside a running asyncio loop
When the first patch schedules a debounced flush task
And the second patch arrives before the task wakes
Then _schedule_flush cancels the existing self._flush_task
And replaces it with a fresh task scheduled for FLUSH_DELAY_S from the second call
And only the most recent state is written to disk when the task finally fires
```

#### UC-CFG-RUNTIME-4: parse_patch rejects unknown top-level keys

```
Given a raw JSON body {"tts": {"enabled": true}, "weather": "sunny"}
When RuntimeSettings.parse_patch(raw) is called
Then the helper computes unknown_top = {"weather"} (anything not in {"tts"})
And raises ValueError("Unknown settings keys: ['weather']")
And no SettingsPatch is returned
```

#### UC-CFG-RUNTIME-5: parse_patch rejects unknown keys inside the tts block

```
Given a raw JSON body {"tts": {"enabled": true, "volume": 0.8}}
When parse_patch(raw) is called
Then the helper validates {"tts"} subset succeeds
And inspects raw["tts"], finds unknown_tts = {"volume"}
And raises ValueError("Unknown tts keys: ['volume']")
```

#### UC-CFG-RUNTIME-6: parse_patch rejects non-boolean enabled

```
Given a raw JSON body {"tts": {"enabled": "true"}}
When parse_patch(raw) is called
Then the helper finds raw["tts"]["enabled"] is a str, not a bool
And raises ValueError("tts.enabled must be a boolean")
And no implicit coercion of "true" -> True is performed
```

#### UC-CFG-RUNTIME-7: parse_patch rejects non-object top-level payload

```
Given a raw JSON body that parsed into a list, string, or None
When parse_patch(raw) is called
Then isinstance(raw, dict) is False
And ValueError("Expected JSON object") is raised
```

#### UC-CFG-RUNTIME-8: parse_patch rejects non-object tts section

```
Given a raw JSON body {"tts": true}
When parse_patch(raw) is called
Then top-level key check passes
And isinstance(raw["tts"], dict) is False
And ValueError("tts must be an object") is raised
```

#### UC-CFG-RUNTIME-9: parse_patch with "tts" key omitted from enabled produces a None patch

```
Given a raw JSON body {"tts": {}}
When parse_patch(raw) is called
Then unknown_tts is empty
And "enabled" is not in tts_raw, so enabled_val is set to None
And SettingsPatch(tts=TTSSettingsPatch(enabled=None)) is returned
And a subsequent patch() call with this payload raises "No mutable settings in patch"
```

#### UC-CFG-RUNTIME-10: Startup replays persisted tts.enabled into the TTS manager

```
Given the JSON state file at settings_path exists and contains {"tts": {"enabled": true}}
When RuntimeSettings(settings_path, tts_manager) is constructed
Then __init__ stores the path and the tts_manager reference
And initialises self._state = SettingsState(tts=TTSSettings(enabled=tts_manager.enabled))
And then calls _load_from_disk()
And _read_settings_file reads the JSON, returns the parsed dict
And the bool True is replayed: self._state.tts.enabled = True, tts_manager.enabled = True
```

#### UC-CFG-RUNTIME-11: Startup with missing state file leaves seeded state intact

```
Given settings_path does NOT exist on disk
When RuntimeSettings(settings_path, tts_manager) is constructed
Then _read_settings_file returns None
And _load_from_disk early-returns without mutating state
And the state stays as initialised from tts_manager.enabled at construction time
```

#### UC-CFG-RUNTIME-12: Startup with malformed JSON is swallowed via logger.exception

```
Given settings_path exists but contains invalid JSON (or is a non-dict JSON value)
When RuntimeSettings(...) is constructed
Then _read_settings_file's try/except catches the parse error
And logger.exception("Failed to read runtime settings from %s", settings_path) is emitted
And the helper returns None
And _load_from_disk skips the replay, leaving the seeded state intact
And construction succeeds — the runtime continues without prior persistence
```

#### UC-CFG-RUNTIME-13: Persistence outside an asyncio loop is a no-op

```
Given _schedule_flush is called from a synchronous context with no running loop
When asyncio.get_running_loop() raises RuntimeError
Then _schedule_flush catches the RuntimeError
And returns silently — no task is created
And the in-memory mutation from the prior patch() call still stands
And the disk file is NOT updated for that call (will be updated by the next patch() that runs under a loop)
```

#### UC-CFG-RUNTIME-14: Flush failure is logged, not raised

```
Given a debounced flush task fires _flush_to_disk
And the write to settings_path raises (disk full, permission denied, etc.)
When the exception propagates inside _flush_to_disk's try block
Then logger.exception("Failed to flush runtime settings to disk") is emitted
And the exception is swallowed
And the in-memory state remains correct; only the on-disk cache is stale
```

#### UC-CFG-RUNTIME-15: Flush writes the full state shape, not a diff

```
Given a successful debounced flush
When _flush_to_disk runs
Then it ensures self._settings_path.parent exists via mkdir(parents=True, exist_ok=True)
And builds payload = {"tts": {"enabled": <current bool>}}
And writes f"{json.dumps(payload, indent=2, sort_keys=True)}\n" with utf-8 encoding
And logger.info("Runtime settings flushed to %s", settings_path) is emitted on success
```

### Implementation pointers (v1)

- `teleclaude/config/runtime_settings.py:18` — `FLUSH_DELAY_S = 0.5` debounce constant.
- `teleclaude/config/runtime_settings.py:21-46` — dataclass shapes (`TTSSettings`, `SettingsState`, `TTSSettingsPatch`, `SettingsPatch`).
- `teleclaude/config/runtime_settings.py:49-61` — `RuntimeSettings.__init__` (seeds state from tts_manager, replays from disk).
- `teleclaude/config/runtime_settings.py:72-87` — `patch` (synchronous in-memory + tts_manager update; raises on empty patch; schedules flush).
- `teleclaude/config/runtime_settings.py:89-119` — `parse_patch` (strict JSON-shape validator: top-level dict check, allowed key set, nested tts dict check, allowed key set, bool type check on enabled).
- `teleclaude/config/runtime_settings.py:121-142` — `_load_from_disk` and `_read_settings_file` (best-effort startup replay; logger.exception on failure).
- `teleclaude/config/runtime_settings.py:144-166` — `_schedule_flush`, `_debounced_flush`, `_flush_to_disk` (asyncio task lifecycle; loop-absence no-op; persist-failure swallowed).

### Cross-context references

- **Cross-context write into the TTS manager.** `RuntimeSettings.patch`
  reaches into a different bounded context — the TTS manager
  (`teleclaude.tts.manager.TTSManager`) — and mutates its `enabled`
  attribute directly. The relationship is "config owns the toggle; TTS
  owns the consumption". In v1 the coupling is a direct attribute write
  held together by convention; in v2 the same coordination would flow
  through a `config.effective.updated` event consumed by the TTS context.
- **Distinct from the YAML overlays.** The `tts` block in `teleclaude.yml`
  (and in legacy `config.yml`) defines boot-time TTS shape — voices,
  services, event mappings, the initial `enabled` value seeded into
  `TTSManager`. `RuntimeSettings` does NOT mutate those YAML files. The
  JSON state file is a separate persistence surface.
- **No domain event in v1.** A patch does not emit `config.effective.updated`
  or any other event. Consumers other than the TTS manager learn about a
  toggle only by reading `tts_manager.enabled` directly.

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
- **No fsync on flush.** The flush calls `write_text`; there is no
  `os.fsync` and no atomic-replace pattern. A power loss mid-write can
  truncate the JSON file. On the next startup, `_read_settings_file`
  detects malformed JSON, logs the failure, and falls back to the
  TTS-manager's boot-time value.
- **Loop-absence is silent.** If `patch()` runs in a sync context with no
  asyncio loop, the mutation is applied in memory but persistence is
  skipped without warning. Operator-facing code is expected to run under
  the daemon's event loop; a CLI that mutated settings outside the daemon
  would lose its writes until the next loop-bound patch.
- **Patches replace, never merge nested partials.** `parse_patch` accepts
  only the `enabled` field today, so the surface is too narrow for a true
  merge problem to surface. When the surface grows, the patch protocol
  will need to clarify "set explicitly" vs. "leave unchanged" semantics
  beyond the current `None` sentinel.
- **`SettingsState` is mutable and exposed via `get_state()`.** A consumer
  that holds the returned `SettingsState` reference observes future
  mutations from `patch()` automatically (and could in principle mutate the
  state directly, bypassing `patch()`'s tts_manager dual-write). v1 relies
  on callers to treat the returned state as read-only.
- **No teardown for the debounced task.** If the owning event loop shuts
  down with a pending `_flush_task`, the task is cancelled by the loop's
  shutdown logic; v1 does not expose an explicit `aclose()` to await the
  final flush deterministically.
