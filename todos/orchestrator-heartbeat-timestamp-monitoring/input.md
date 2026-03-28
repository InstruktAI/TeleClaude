# orchestrator-heartbeat-timestamp-monitoring — Input

Replace the current orchestration fallback for worker-progress detection with a deterministic heartbeat rule based on existing session-list fields.

Core rule:
- Source of truth is telec sessions list.
- Compare only these two fields per worker session:
  - last_activity
  - last_output_summary_at
- Interpretation:
  - last_activity > last_output_summary_at => worker is still active/progressing
  - last_activity == last_output_summary_at => worker is idle/settled
- This replaces the current fallback logic entirely.
- Remove the Codex-specific two-heartbeat / observation-action protocol.
- Remove the old repeated-idle-heartbeat fallback. It is superseded by the deterministic timestamp comparison.
- A notification is only a heartbeat trigger, not proof of completion.
- A timer is also a heartbeat trigger.
- A manual check is also a heartbeat trigger.
- All heartbeat triggers must run the same assessment logic.

Important constraints:
- Do not invent any new helper/orchestration module unless research proves an existing location cannot hold the logic. Default expectation: change the existing next-machine/orchestration code, not architecture.
- No new DB fields.
- No schema changes.
- No digest-based progress detection. last_output_digest is irrelevant for this design.
- Stick to the existing telec sessions list payload and existing orchestration surfaces.

Likely production files to research:
- teleclaude/core/next_machine/output_formatting.py
- teleclaude/core/session_listeners.py
- teleclaude/api/sessions_routes.py
- teleclaude/core/models/_snapshot.py

Expected production change direction:
- teleclaude/core/next_machine/output_formatting.py
  - remove the current Codex two-heartbeat wording/instructions
  - replace with the timestamp comparison rule and heartbeat-trigger wording
- teleclaude/core/session_listeners.py
  - research whether notification wording should stop implying completion (for example, "finished its turn" currently suggests too much)
- teleclaude/api/sessions_routes.py / teleclaude/core/models/_snapshot.py
  - likely no behavior change needed, but prepare must verify that sessions list already exposes the required fields and scoping behavior

Very important testing policy requirement:
- No string tests. No prose-lock tests. No exact human-facing output assertions on this path.
- Remove all rendered-string tests on the relevant next_machine/orchestration path.
- Prepare must research exact replacements or deletions, but the direction is mandatory: these string tests must be removed from scope.

Known test files on the code path that currently contain rendered-string/prose-lock assertions and must be researched for removal or rewrite:
- tests/unit/core/next_machine/test_output_formatting.py
  - likely delete entirely; it is dominated by rendered instruction assertions
- tests/unit/core/next_machine/test_core.py
  - remove prose-lock assertions around formatted instructions / dispatch text / blocked text / dispatch markers
- tests/unit/core/next_machine/test_work.py
  - remove prose assertions on returned error/dispatch text
- tests/unit/core/next_machine/test_prepare.py
  - remove prose assertions on returned dispatch/container text
- tests/unit/core/next_machine/test_prepare_steps.py
  - remove prose assertions on instruction text and dispatch wording
- tests/unit/core/next_machine/test_create.py
  - remove prose assertion on dispatch string
- tests/unit/core/next_machine/test_build_gates.py
  - remove prose assertion(s), including format_build_gate_failure output expectations

Preparation worker should:
- trace the current orchestration path end to end
- confirm the exact places where the old fallback logic lives
- identify all prose-lock tests in the affected path
- decide, per test, whether it should be deleted outright or converted to a structural/non-prose assertion
- produce a prepared todo with concrete implementation plan and test cleanup plan

Do not weaken the core requirement in preparation:
- deterministic timestamp comparison replaces fallback heuristics
- no string tests on this path
