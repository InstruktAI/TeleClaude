# Demo: identity-origin-cleanup

## Medium

CLI + test output. All behavioral changes are internal to the session creation
pipeline — no new UI surface. Verification is via the test suite and targeted
behavioral checks.

## What the user observes

After this change, session creation through web and terminal API routes passes
typed origin metadata (WebOriginMetadata, TerminalOriginMetadata) through the
full pipeline: command → handler → identity resolver → DB. The `working_slug`
field is derived from the subdir convention rather than passed explicitly.

## Validation

### 1. Typed origin metadata flows through the handler

```bash
pytest tests/unit/core/test_channel_metadata_cleanup.py -v
```

Expected: All tests PASSED.

### 2. working_slug derivation from subdir pattern

```bash
pytest tests/unit/core/test_working_slug_derivation.py -v
```

Expected: All 3 tests PASSED — trees/slug derives, non-trees yields None, absent yields None.

### 3. Typed origin metadata types exist and implement Mapping

```bash
python -c "
from teleclaude.core.models._adapter import WebOriginMetadata, TerminalOriginMetadata
w = WebOriginMetadata(email='test@example.com')
t = TerminalOriginMetadata(email='admin@example.com')
print(f'Web: {w.to_dict()}')
print(f'Terminal: {t.to_dict()}')
print(f'Web.get(email): {w.get(\"email\")}')
"
```

Expected:

```
Web: {'email': 'test@example.com'}
Terminal: {'email': 'admin@example.com'}
Web.get(email): test@example.com
```

### 4. CreateSessionCommand accepts typed origin_metadata

```bash
python -c "
from teleclaude.types.commands import CreateSessionCommand
from teleclaude.core.models._adapter import WebOriginMetadata
cmd = CreateSessionCommand(project_path='/tmp', origin='web', origin_metadata=WebOriginMetadata(email='test@example.com'))
print(f'origin_metadata type: {type(cmd.origin_metadata).__name__}')
print(f'email: {cmd.origin_metadata[\"email\"]}')
"
```

Expected:

```
origin_metadata type: WebOriginMetadata
email: test@example.com
```

### 5. Full test suite passes

```bash
make test
```

Expected: All tests PASSED.
