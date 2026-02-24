# Review Findings: adapter-output-delivery

REVIEW COMPLETE: adapter-output-delivery

Verdict: REQUEST CHANGES

Findings: 3

Critical:

- None.

Important:

- `teleclaude/core/agent_coordinator.py` and `teleclaude/core/command_handlers.py` require strict single-send reflection behavior (no duplicate headless/non-headless reflection paths).
- `teleclaude/core/adapter_client.py` must preserve required reflection header contract (`"SOURCE @ computer"`) while still supporting actor attribution.
- `todos/adapter-output-delivery/implementation-plan.md` remains with unchecked tasks while `todos/adapter-output-delivery/state.yaml` reports completed build, so plan/task bookkeeping is currently inconsistent.

Suggestions:

- Keep one reflection path per input event and test both lifecycle modes.
- Preserve required attribution format and avoid silent behavioral drift.
- Update plan checkboxes or add justified deferrals before re-review.

Contract addendum:

- MCP-origin suppression is superseded by product decision: MCP is provenance only and does not suppress reflection routing.
- Ownership attribution for MCP-origin messages must resolve via lineage (human owner when present, otherwise system owner).
