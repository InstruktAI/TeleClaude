---
description: 'Steps to add a new adapter implementation and wire it into the daemon.'
id: 'project/procedure/add-adapter'
scope: 'project'
type: 'procedure'
---

# Add Adapter — Procedure

## Goal

- Add a new adapter and wire it into the daemon.

## Preconditions

- Adapter type and responsibilities are defined.

## Steps

1. Create a new adapter class inheriting `BaseAdapter` (and `UiAdapter` or `RemoteExecutionProtocol` as needed).
2. Implement `start`/`stop` and required messaging or transport methods.
3. Add configuration keys to `config.sample.yml`.
4. Register adapter env vars in `_ADAPTER_ENV_VARS` in `teleclaude/cli/config_handlers.py`.
5. Register adapter field guidance in `GuidanceRegistry` in `teleclaude/cli/tui/config_components/guidance.py`.
6. Verify the config wizard discovers and exposes the new adapter area.
7. Update `docs/project/spec/teleclaude-config.md` with the new config keys and env vars.
8. Register the adapter in `AdapterClient.start()` based on config.
9. Add tests to validate routing and adapter behavior.

## Outputs

- Adapter is discoverable, starts successfully, and routes through `AdapterClient`.

## Recovery

- If the adapter does not start, verify config keys and registration in `AdapterClient`.
