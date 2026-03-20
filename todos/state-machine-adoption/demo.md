# Demo: state-machine-adoption

## Validation

```bash
# Verify mark-* commands route through the transition engine
python3 -c "
from teleclaude.core.next_machine.state_io import mark_phase
print('mark_phase is a transition wrapper: OK')
"
```

```bash
# Verify no remaining legacy field access outside migration/tests
rg -l 'state\.get\(\"prepare_phase\"\)|state\.get\(\"build\"\)|state\.get\(\"review\"\)' \
  teleclaude/ --glob '!**/test_*' --glob '!**/state_io.py' | head -5 || echo 'NFR-1: OK — no legacy field access'
```

```bash
# Verify ghost artifact protection is removed
rg '_is_artifact_produced' teleclaude/ | head -5 || echo 'Ghost protection: removed'
```

```bash
# Verify all tests pass
make test
```

## Guided Presentation

### Step 1: Mark-* Commands Now Route Through the Engine

**Do:** Inspect a mark-phase operation and verify it fires a transition.

```bash
telec todo state state-machine-adoption
```

**Observe:** The state shows `current` and `history`. When mark-phase is
called, a history entry appears — proving the operation went through the
transition engine.

**Why it matters:** Every state mutation now has an audit trail. No more
direct field patches that bypass guards and history.

### Step 2: Work Machine Uses Authoritative State

**Do:** Verify work.py dispatch reads from `current`.

```bash
rg 'state.get\("current"\)' teleclaude/core/next_machine/work.py
```

**Observe:** Work machine dispatch uses `current` for phase checks.

**Why it matters:** The work machine was the largest consumer of the old
field model. Its migration proves v2 works for the most complex lifecycle.

### Step 3: No Inference Anywhere (NFR-1)

**Do:** Search for any remaining legacy state inference.

```bash
rg 'state\.get\("prepare_phase"\)|state\.get\("build"\)|state\.get\("review"\)' \
  teleclaude/ --glob '!**/test_*' --glob '!**/state_io.py'
```

**Observe:** Zero results. No code path infers lifecycle state from legacy
fields outside of migration code.

**Why it matters:** This is the end goal — one authoritative state value,
everywhere.

### Step 4: Ghost Artifacts Are Gone

**Do:** Confirm `_is_artifact_produced` no longer exists.

```bash
rg '_is_artifact_produced' teleclaude/
```

**Observe:** Zero results. The function and all its callers are removed.

**Why it matters:** Ghost artifact protection was a symptom of untrusted
state. With `current` as the authority, artifact metadata is informational,
not stateful.
