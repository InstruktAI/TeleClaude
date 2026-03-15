# Demo: chartest-adapters-discord

## Validation

Confirm every Discord adapter source file now has a matching characterization test file.

```bash
. .venv/bin/activate && python - <<'PY'
from pathlib import Path

expected = [
    "tests/unit/adapters/test_base_adapter.py",
    "tests/unit/adapters/test_discord_adapter.py",
    "tests/unit/adapters/discord/test_channel_ops.py",
    "tests/unit/adapters/discord/test_gateway_handlers.py",
    "tests/unit/adapters/discord/test_infra.py",
    "tests/unit/adapters/discord/test_input_handlers.py",
    "tests/unit/adapters/discord/test_message_ops.py",
    "tests/unit/adapters/discord/test_provisioning.py",
    "tests/unit/adapters/discord/test_relay_ops.py",
    "tests/unit/adapters/discord/test_session_launcher.py",
    "tests/unit/adapters/discord/test_team_channels.py",
]

missing = [path for path in expected if not Path(path).exists()]
if missing:
    raise SystemExit(f"Missing test files: {missing}")

print(f"Verified {len(expected)} characterization test files.")
PY
```

Run the full Discord adapter characterization slice.

```bash
. .venv/bin/activate && pytest \
  tests/unit/adapters/test_base_adapter.py \
  tests/unit/adapters/test_discord_adapter.py \
  tests/unit/adapters/discord/test_channel_ops.py \
  tests/unit/adapters/discord/test_gateway_handlers.py \
  tests/unit/adapters/discord/test_infra.py \
  tests/unit/adapters/discord/test_input_handlers.py \
  tests/unit/adapters/discord/test_message_ops.py \
  tests/unit/adapters/discord/test_provisioning.py \
  tests/unit/adapters/discord/test_relay_ops.py \
  tests/unit/adapters/discord/test_session_launcher.py \
  tests/unit/adapters/discord/test_team_channels.py \
  -q
```

## Guided Presentation

Start with the mapping block and point out that every source file named in the todo now has a concrete test file under `tests/unit/`.

Then run the pytest block and call out that the suite is characterization coverage, not production changes: it pins current adapter behavior around metadata storage, routing, launcher callbacks, relay parsing, and provisioning persistence.

When the run finishes, note that the delivery leaves production code untouched and adds a regression net around the Discord adapter surface for future refactors.
