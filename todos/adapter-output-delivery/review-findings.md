# Review Findings: adapter-output-delivery

REVIEW COMPLETE: adapter-output-delivery

Verdict: REQUEST CHANGES

Findings: 4

Critical:

- None.

Important:

- `teleclaude/core/agent_coordinator.py:430-461` and `teleclaude/core/command_handlers.py:892-901` cause headless terminal hook input to be reflected twice because `handle_user_prompt_submit()` always calls `client.broadcast_user_input(..., source="hook")` and still calls `get_command_service().process_message(cmd)`, while `process_message()` also calls `client.broadcast_user_input()` for any `cmd.origin`.
- `teleclaude/core/adapter_client.py:589-591` changed user reflection format from `"{SOURCE} @ {computer_name}:\n\n{text}"` to `"{normalized_actor_name}:\n\n{text}"`, removing the computer-name attribution required by `todos/adapter-output-delivery/requirements.md` success criterion 3 (`TUI @ {computer_name}:\n\n{text}` for terminal input).
- `teleclaude/core/command_handlers.py:892-901` (paired with `broadcast_user_input`) now reflects all command origins, including MCP, and there is no MCP guard before broadcast, violating `todos/adapter-output-delivery/requirements.md` success criterion 5 (`MCP-origin input is still NOT broadcast`).
- `todos/adapter-output-delivery/implementation-plan.md` remains with unchecked tasks while `todos/adapter-output-delivery/state.yaml` still reports `build: complete`, with no `todos/adapter-output-delivery/deferrals.md`, so planned work and deferral status were not verified before review.

Suggestions:

- Remove duplicate hook reflection path by limiting reflection to one path in `handle_user_prompt_submit` for headless sessions.
- Restore required `"SOURCE @ computer"` reflection header.
- Add explicit MCP-origin suppression for reflection (either in `process_message()` or upstream mapping).
- Update plan checkboxes or add justified deferrals in `deferrals.md` before review.
