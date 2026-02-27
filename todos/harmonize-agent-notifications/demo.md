# Demo: harmonize-agent-notifications

## Validation

```bash
python -c "from teleclaude.core.activity_contract import HOOK_TO_CANONICAL; assert HOOK_TO_CANONICAL.get('notification') == 'agent_notification'; print('OK: notification mapped')"
```

```bash
python -c "from teleclaude.core.activity_contract import serialize_activity_event; e = serialize_activity_event('s1', 'notification', '2026-01-01T00:00:00Z', message='hello'); assert e and e.canonical_type == 'agent_notification' and e.message == 'hello'; print('OK: serializer works')"
```

```bash
make test
```

## Guided Presentation

1. **Mapping**: `activity_contract.py` — `notification` now maps to `agent_notification`. Previously unmapped and silently dropped.
2. **Coordinator**: `agent_coordinator.py` `handle_notification()` — now emits a canonical activity event with the plucked `message` field after existing listener logic.
3. **Vocabulary**: `event-vocabulary.md` — `agent_notification` documented with `message` payload field.
