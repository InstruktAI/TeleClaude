# Demo: origin-metadata-rename

## Validation

```bash
# R4: No channel_metadata in production code
grep -rn "channel_metadata" teleclaude/ | grep -v "__pycache__" | grep -v ".pyc" && echo "FAIL: channel_metadata still present" || echo "PASS: fully renamed to origin_metadata"
```

```bash
# R4/R5: RedisTransportMetadata backward compat — from_dict accepts old key
python3 -c "
from teleclaude.core.models._adapter import RedisTransportMetadata
m = RedisTransportMetadata.from_dict({'channel_metadata': '{\"user_id\": \"123\"}'})
assert m.origin_metadata is not None, 'backward compat failed'
print('PASS: backward compat works')
"
```

```bash
# Quality gate: all tests pass
make test 2>&1 | tail -5
```

```bash
# Quality gate: lint and typecheck pass
make lint 2>&1 | tail -5
```

## Guided Presentation

### Step 1: Naming convergence — channel_metadata removed

Show that `channel_metadata` no longer appears in production code.

**What to do:** Run `grep -rn "channel_metadata" teleclaude/ --include="*.py"`.

**What to observe:** Zero production hits. The `RedisTransportMetadata.from_dict`
method still accepts the old key for backward compatibility.

**Why it matters:** R4 — single consistent naming per the layer-ownership architecture.

### Step 2: Actor extraction still works

Show that actor identity extraction produces the same results via the renamed path.

**What to do:** Show `CommandMapper._extract_actor` reading from `origin_metadata`.
Run the actor extraction tests.

**What to observe:** Tests pass. Actor identity is extracted identically.

**Why it matters:** R5 — behavioral preservation for the most critical downstream
consumer.

### Step 3: Redis transport round-trip

Show that Redis transport metadata serializes with the new key and deserializes
from both old and new keys.

**What to do:** Run `tests/unit/core/models/test__adapter.py`.

**What to observe:** `to_dict()` outputs `origin_metadata`. `from_dict()` accepts
both keys.

**Why it matters:** Prevents deserialization failures for data from older daemon
versions.

### Step 4: Test suite passes

**What to do:** Run `make test`.

**What to observe:** All tests pass.

**Why it matters:** R5 — behavioral preservation across the full pipeline.
