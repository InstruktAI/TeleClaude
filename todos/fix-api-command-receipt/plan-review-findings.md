# Plan Review Findings: fix-api-command-receipt

## Critical

1. Plan approval is blocked by an unapproved requirements baseline. `state.yaml` still records `requirements_review: needs_work`, and the three open findings remain material: `requirements.md` still omits the DELETE-session remote-routing/close coverage from `input.md`, the `notification_claimed` and `notification_resolved` events, and the required documentation deliverables. The review-plan precondition is not satisfied.

2. Task 2 does not satisfy FR-2. The requirements and [command-classification.md](/Users/Morriz/Workspace/InstruktAI/TeleClaude/docs/project/design/architecture/command-classification.md) require execution behavior to derive from `command.response_mode`, but Task 2 replaces `isinstance` checks with `command_type` dispatch tables in [\_messaging.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/transport/redis_transport/_messaging.py) and [private_handlers.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/adapters/telegram/private_handlers.py). That still requires dispatcher edits when a new command type is added and does not plan the required mode-driven execution branch.

3. Task 3 leaves the RECEIPT contract incomplete. The current receipt surface in [api_models.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/api_models.py) and [service.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/core/operations/service.py) has no `completion_event`, and the plan never adds it to `OperationStatusDTO`, `OperationStatusPayload`, `SerializedOperation`, or the terminal operation path. That contradicts FR-3 and [operation-receipts.md](/Users/Morriz/Workspace/InstruktAI/TeleClaude/docs/project/design/architecture/operation-receipts.md), which require a terminal completion event for receipt-backed operations.

4. Task 6 contradicts both the requirements and the rest of the plan. The requirements preserve the response codes and shapes of endpoints marked "already correct," but Task 6 changes `POST /sessions/{id}/keys`, `POST /sessions/{id}/voice`, and `POST /sessions/self/file` to `202`. At the same time, Task 1 classifies `ProcessMessageCommand` as `FIRE_AND_FORGET`, while Task 6 leaves `POST /sessions/{id}/message` at `200`. The plan cannot be executed coherently until that response-mode matrix is corrected.

## Important

1. Task 5 leaves the `SystemCommand` seam unresolved. [command_service.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/core/command_service.py) has no typed entrypoint for session-scoped `SystemCommand` operations, and the current `system_command` event path is daemon-level, not session mutation delivery. The plan’s "if needed" wording leaves the builder to invent the dispatch seam.

2. Verification still fails the test-spec gate. `state.yaml` has no produced `test_specs` artifact, and the plan only uses generic "Expected-failure spec" bullets instead of naming the actual expected-failure tests each task will make green. Under the testing policy and plan-review procedure, that is not a sufficient execution contract.

3. The plan does not cover demo updates for user-visible API changes. This work changes HTTP status codes, response bodies, and receipt behavior, and [quality-checklist.md](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/fix-api-command-receipt/quality-checklist.md) requires demo validation, but no task or verification step covers `demo.md`.

## Suggestion

- None.
