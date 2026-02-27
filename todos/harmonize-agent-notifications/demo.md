# Demo: harmonize-agent-notifications

## Validation

```bash
python -c "from teleclaude.core.activity_contract import HOOK_TO_CANONICAL; assert HOOK_TO_CANONICAL['notification'] == 'agent_notification'; assert HOOK_TO_CANONICAL['error'] == 'agent_error'; print('OK: both hooks mapped')"
```

```bash
python -c "from teleclaude.core.activity_contract import serialize_activity_event; e = serialize_activity_event('s1', 'notification', '2026-01-01T00:00:00Z', message='hello'); assert e and e.canonical_type == 'agent_notification' and e.message == 'hello'; print('OK: notification serializer')"
```

```bash
python -c "from teleclaude.core.activity_contract import serialize_activity_event; e = serialize_activity_event('s1', 'error', '2026-01-01T00:00:00Z', message='something broke'); assert e and e.canonical_type == 'agent_error' and e.message == 'something broke'; print('OK: error serializer')"
```

```bash
make test
```

## Guided Presentation

1. **Mapping**: `activity_contract.py` — `notification` and `error` now map to canonical types. Previously both were unmapped and silently dropped.
2. **Coordinator**: `handle_notification()` emits a canonical activity event. New `handle_error()` does the same for error hooks which previously had no handler at all.
3. **Vocabulary**: `event-vocabulary.md` — both `agent_notification` and `agent_error` documented.
