---
description: 'Steps to add a new adapter implementation and wire it into the daemon.'
visibility: 'public'
---

# Add Adapter — Procedure

## Goal

- Add a new adapter and wire it into the daemon.

## Preconditions

- Adapter type and responsibilities are defined.

- A non-Discord adapter is a conversational input→response surface. It does not
  expose session-control, operator-console, or admin-channel lifecycle actions;
  Discord remains the sole admin adapter.

## Steps

1. Create a new adapter class inheriting `BaseAdapter` (and `UiAdapter` or `RemoteExecutionProtocol` as needed).
   For a human-facing adapter other than Discord, implement only identity or
   invitation binding, conversational input modalities, and delivery of the
   session response to the origin endpoint.
2. Implement `start`/`stop` and required messaging or transport methods.
3. Declare the adapter's configuration fields on the machine-config schema, marking credential fields sensitive.
4. Mark credential fields sensitive so their environment variables derive from the field paths; mark fields `tui` to admit them to the config TUI. The two markers are independent.
5. Verify the config wizard discovers and exposes the new adapter area.
6. Update `docs/local/spec/teleclaude-config.md` with the new config keys and env vars.
7. Register the adapter in `AdapterClient.start()` based on config.
8. Add tests to validate routing and adapter behavior.

## Outputs

- Adapter is discoverable, starts successfully, and routes through `AdapterClient`.

## Recovery

- If the adapter does not start, verify config keys and registration in `AdapterClient`.
