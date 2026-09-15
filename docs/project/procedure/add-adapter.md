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
<!-- planned-change:config-sample-regeneration-leaves-sync -->
3. Add configuration keys to `templates/config.yml`.
<!-- change:config-sample-regeneration-leaves-sync -->
3. Declare the adapter's configuration fields on the machine-config schema, marking credential fields sensitive.
<!-- /planned-change:config-sample-regeneration-leaves-sync -->
<!-- planned-change:config-sample-regeneration-leaves-sync -->
4. Register adapter env vars in `_ADAPTER_ENV_VARS` in `teleclaude/cli/config_handlers.py`.
5. Register adapter field guidance in `GuidanceRegistry` in `teleclaude/cli/tui/config_components/guidance.py`.
<!-- change:config-sample-regeneration-leaves-sync -->
4. Mark credential fields sensitive so their environment variables derive from the field paths; mark fields `tui` to admit them to the config TUI. The two markers are independent.
<!-- /planned-change:config-sample-regeneration-leaves-sync -->
6. Verify the config wizard discovers and exposes the new adapter area.
7. Update `docs/project/spec/teleclaude-config.md` with the new config keys and env vars.
8. Register the adapter in `AdapterClient.start()` based on config.
9. Add tests to validate routing and adapter behavior.

## Outputs

- Adapter is discoverable, starts successfully, and routes through `AdapterClient`.

## Recovery

- If the adapter does not start, verify config keys and registration in `AdapterClient`.
