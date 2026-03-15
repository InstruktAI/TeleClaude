# Demo: chartest-core-adapter-client

## Validation

```bash
.venv/bin/pytest tests/unit/core/adapter_client/ -q --tb=short
```

## Guided Presentation

The delivery adds 74 characterization tests across 4 test files, one per source module:

- `test__channels.py` — pins `_summarize_output`, `_format_event_text`, pre/post command handlers, `send_general_message`
- `test__client.py` — pins `AdapterClient` init, adapter registration, UI filtering, stop/fanout/broadcast
- `test__output.py` — pins `send_error_feedback`, `delete_channel`, `edit_message`, `delete_message`, `send_file`, `send_message`, `update_channel_title`
- `test__remote.py` — pins `discover_peers` (deduplication, redis-disabled, error tolerance), `send_request`, `send_response`, `read_response`, `_get_transport_adapter`

These tests form a regression safety net against unintended behavior changes during future refactoring.
