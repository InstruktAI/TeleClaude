# Demo: identity-origin-cleanup-final

## Medium

CLI — all verification is command-line observable via grep, test output, and pyright.

## What the user observes

The legacy per-message actor bag, the legacy terminal identity helper, and the direct
headless DB bypass are gone from the live code paths. Actor identity now flows through
typed fields end to end: adapter -> `MessageMetadata` -> `CommandMapper` ->
`ProcessMessageCommand`. Headless session creation goes through the standard command
pipeline.

## Validation

```bash
legacy_actor_bag="$(printf '%s_%s' channel metadata)"
legacy_terminal_helper="$(printf '%s_%s_%s' resolve from terminal)"
legacy_headless_creator="$(printf '%s_%s_%s' create headless session)"

if grep -r "$legacy_actor_bag" teleclaude/ tests/ docs/ demos/; then
  echo "FAIL: legacy actor bag still present"
  exit 1
fi

if grep -r "$legacy_terminal_helper" teleclaude/ tests/; then
  echo "FAIL: legacy terminal helper still present"
  exit 1
fi

if grep -r "$legacy_headless_creator" teleclaude/ tests/; then
  echo "FAIL: legacy headless creator still present"
  exit 1
fi

echo "PASS: legacy names eliminated from checked scopes"
```

```bash
pytest \
  tests/unit/test_daemon_headless_pipeline.py \
  tests/unit/test_adapter_actor_normalization.py \
  tests/unit/transport/redis_transport/test_redis_wire_format_typed_fields.py \
  tests/unit/transport/redis_transport/test_target_computer_named_field.py \
  tests/unit/core/command_handlers/test__session.py \
  tests/unit/core/test_session_launcher.py \
  -v --tb=short
```

```bash
python - <<'PY'
from teleclaude.core.models._session import MessageMetadata
from teleclaude.core.models._snapshot import RedisInboundMessage
from teleclaude.core.identity import IdentityResolver

legacy_actor_bag = "_".join(["channel", "metadata"])
legacy_terminal_helper = "_".join(["resolve", "from", "terminal"])

assert legacy_actor_bag not in MessageMetadata.__dataclass_fields__
assert legacy_actor_bag not in RedisInboundMessage.__dataclass_fields__
assert hasattr(MessageMetadata(), "actor_id")
assert hasattr(MessageMetadata(), "actor_name")
assert hasattr(MessageMetadata(), "actor_avatar_url")
assert hasattr(MessageMetadata(), "platform_message_id")
assert not hasattr(IdentityResolver(), legacy_terminal_helper)

print("PASS: typed actor fields and standard identity path are active")
PY
```

```bash
make lint
make test
```
