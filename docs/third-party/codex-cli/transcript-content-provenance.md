---
description: Codex CLI rollout content provenance — positional content_item_kinds, runtime-owned user-role fragments, legacy recognition, and observed version behavior.
---

# Codex CLI Transcript Content Provenance

## Evidence boundary

Codex CLI persists model-facing conversation material in rollout JSONL files under
`~/.codex/sessions/YYYY/MM/DD/*.jsonl`. OpenAI does not publish the rollout file as a
public compatibility API. The public Codex documentation does not define its record
schema, and current upstream source calls the relevant field internal Responses API
passthrough metadata and excludes it from generated public schemas.

This profile therefore records observed and source-grounded compatibility evidence,
not a vendor stability promise:

- installed runtime verified on 2026-09-03: Codex CLI `0.151.0`;
- local rollout corpus inspected: CLI `0.148.0` through `0.151.0`;
- current upstream source inspected at commit
  `728cb12fe5794b0c3a8e776fb4994b1650b973a8` on 2026-09-03;
- merged upstream provenance work: pull requests 40174, 40180, and 40196.

Consumers must tolerate missing, malformed, reordered, and newly introduced
classifications. Version numbers alone do not prove that annotations are present: the
field was feature-gated during rollout, legacy messages remain readable, and malformed
metadata is deliberately loaded as absent.

## Wire shape

A model-facing message is stored as a `response_item` whose payload contains a role and
an ordered `content` array. When present,
`payload.internal_chat_message_metadata_passthrough.content_item_kinds` is an ordered
array aligned positionally with that content array:

```json
{
  "type": "response_item",
  "payload": {
    "type": "message",
    "role": "user",
    "content": [{ "type": "input_text", "text": "..." }],
    "internal_chat_message_metadata_passthrough": {
      "turn_id": "...",
      "create_time": 0,
      "content_item_kinds": ["user.text"]
    }
  }
}
```

`ContentItemKind` is a transparent string wrapper, not a closed enum. Upstream preserves
unrecognized values on round-trip. Deserialization defaults a malformed
`content_item_kinds` value to absent. Current upstream converts missing positions to the
literal `unknown` while retaining the content; it does not make an unclassified position
human-authored.

The metadata is per content position, not per message. A consumer that concatenates the
content array before reading the aligned classifications destroys the provenance needed
to separate human input from runtime context.

`turn_id` correlates items belonging to a turn. `create_time` records message creation
time. Neither field identifies authorship or distinguishes a person from the harness.

## Authorship facts

The Responses role is not an authorship field. Codex intentionally emits many hidden,
runtime-owned fragments with `role: "user"` because they are model-facing user-context
messages. Therefore `role == "user"` does not mean a person supplied the content.

Current upstream creates direct human input with these explicit kinds:

| Kind         | Content                                       |
| ------------ | --------------------------------------------- |
| `user.text`  | Text supplied through the user-input surface  |
| `user.image` | Image supplied through the user-input surface |
| `user.audio` | Audio supplied through the user-input surface |

These are the positive human-input evidence available in the current source. Every other
known annotation below is harness-, extension-, tool-, agent-, or generated-context
material. An unknown or future value supplies no positive evidence of human authorship.

## Current upstream runtime vocabulary

The vocabulary is open-ended. This inventory records current upstream producers so a
consumer can recognize known non-human material without pretending the list is closed.

### Runtime fragments carried with the user role

| Kind or pattern                             | Producer / meaning                                                                                                    |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `agents_md.instructions`                    | Discovered `AGENTS.md` instructions                                                                                   |
| `environments.environment_context`          | Current environment and workspace context                                                                             |
| `additional_content.<key>`                  | Key-qualified additional context; the same pattern may also use the developer role                                    |
| `<source>.internal_context`                 | Hidden internal model steering, including `goal.internal_context`                                                     |
| `compaction.summary`                        | Generated compaction summary                                                                                          |
| `apply_patch.legacy_exec_command_warning`   | Legacy apply-patch warning retained for old sessions                                                                  |
| `model_switch.legacy_mismatch_warning`      | Legacy model-mismatch warning retained for old sessions                                                               |
| `unified_exec.legacy_process_limit_warning` | Legacy unified-exec process-limit warning                                                                             |
| `guardian.node_repl_review_evidence`        | Generated Guardian review evidence                                                                                    |
| `realtime_conversation.delegation`          | Realtime delegation context                                                                                           |
| `plugins.recommendations`                   | Recommended-plugin context                                                                                            |
| `multi_agent.subagent_notification`         | Generated subagent notification                                                                                       |
| `generic.turn_aborted`                      | Generated interrupted-turn marker                                                                                     |
| `images.unsupported`                        | Generated unsupported-image notice                                                                                    |
| `audio.unsupported`                         | Generated unsupported-audio notice                                                                                    |
| `images.preparation_error`                  | Generated image-preparation failure replacement                                                                       |
| `shell.user_command`                        | Captured user-shell command, exit status, duration, and output; operational evidence rather than conversational input |
| `skills.selected_skill_instructions`        | Selected skill instructions                                                                                           |
| `unknown`                                   | Missing positional classification filled by the harness; not an authorship assertion                                  |

Extension-owned contextual fragments may introduce additional strings and may choose the
user role. Internal model-context sources are deliberately dynamic but constrained to a
lowercase identifier; their kind is derived as `<source>.internal_context`.

### Runtime fragments carried with the developer role

Current upstream source defines or emits these literal kinds and patterns:

- `additional_content.<key>`
- `apps.instructions`
- `collaboration_mode.instructions`
- `compaction.auto_fallback_prompt`
- `current_time.reminder`
- `environments.instructions`
- `generic.developer_instructions`
- `guardian.approved_action`
- `guardian.followup_review_reminder`
- `guardian.node_repl_policy`
- `guardian.policy`
- `guardian.review_evidence`
- `hooks.additional_context`
- `images.resize_notice`
- `managed_config.developer_instructions`
- `model.base_instructions`
- `model_switch.instructions`
- `multi_agent.mode_instructions`
- `multi_agent.role_instructions`
- `multi_agent.usage_hint`
- `network_proxy.rule_saved`
- `permissions.approved_command_prefix_saved`
- `permissions.instructions`
- `personality.spec_instructions`
- `persistent_mode.instructions`
- `plugins.instructions`
- `plugins.usage_instructions`
- `realtime_conversation.custom_start_instructions`
- `realtime_conversation.end_instructions`
- `realtime_conversation.start_instructions`
- `rollout_budget.remaining_tokens`
- `skills.catalog`
- `token_budget.context_window`
- `token_budget.context_window_guidance`
- `token_budget.remaining_tokens`
- `token_budget.reminder`
- `tools.deferred_namespaces`
- `<extension-id>.instructions` for extension-owned world-state fragments

Current extensions also emit open-ended kinds such as `memories.instructions`,
`notes.thread_hint`, `guardian.trusted_skills`, and `guardian.trusted_tool`. The extension
API deliberately permits further values.

### Agent-authored fragments carried with the assistant role

`multi_agent.inter_agent_message` and
`multi_agent.inter_agent_completion_message` are generated inter-agent content. Ordinary
assistant output may have no kind or the compatibility value `unknown`; its assistant
role still makes it agent-authored rather than human-authored.

## Hook prompts

Hook continuation text is a special compatibility case. Current upstream
`build_hook_prompt_message()` creates one or more `role: "user"` input-text blocks wrapped
as `<hook_prompt hook_run_id="...">...</hook_prompt>` and sets
`internal_chat_message_metadata_passthrough` to `None`. When the generic positional
annotation machinery later encounters an unclassified position, it assigns `unknown`.

The rollout corpus agrees: in 189 inspected CLI `0.151.0` transcripts, all 42 user-role
items carrying `content_item_kinds: ["unknown"]` began with `<hook_prompt>`. Therefore
`unknown` is not safe evidence of human input, and the current hook prompt remains a
source-grounded structural fallback even when the annotation feature is enabled.

Upstream parses hook prompts structurally with its XML parser and represents them as a
typed `HookPrompt` turn item during rollout migration. Consumers should not invent a
second semantic interpretation of the hook body.

## Legacy structural recognition

Older rollouts and feature-disabled or malformed records may lack usable annotations.
Current upstream carries a frozen legacy migration predicate for runtime-owned user-role
text. Its recognized shapes are the appropriate compatibility evidence for a bounded
fallback:

- `# AGENTS.md instructions ... </INSTRUCTIONS>`;
- `<environment_context>...</environment_context>`;
- `<skill>...</skill>`;
- `<user_shell_command>...</user_shell_command>`;
- `<turn_aborted>...</turn_aborted>`;
- `<subagent_notification>...</subagent_notification>`;
- `<recommended_plugins>...</recommended_plugins>`;
- legacy `<goal_context>...</goal_context>`;
- `<codex_internal_context source="...">...</codex_internal_context>`;
- matching `<external_<key>>...</external_<key>>` envelopes;
- the legacy unified-exec process-limit warning;
- the legacy apply-patch-via-exec warning;
- the high-risk cyber warning;
- a structurally parseable `<hook_prompt>` with a non-empty `hook_run_id`.

The fallback is whole-fragment recognition: the trimmed text must match the registered
opening and closing shape. Prefix-only or arbitrary XML stripping is not equivalent to
upstream recognition and can erase text a person intentionally supplied.

## Observed version behavior

The local corpus was rescanned on 2026-09-03 after confirming the installed runtime was
Codex CLI `0.151.0`.

| Runtime evidence                 | Observation                                                                                                                                                                                                                                                                                                                          |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `0.148.0`–early `0.149.x`        | Many messages have no `content_item_kinds`; legacy structural recognition is required.                                                                                                                                                                                                                                               |
| `0.149.x` transition             | Annotated and unannotated records coexist, so a version gate alone is insufficient.                                                                                                                                                                                                                                                  |
| `0.150.0`–`0.151.0`              | The observed runtime emits annotations broadly. Current source marks the feature stable and enabled by default.                                                                                                                                                                                                                      |
| 189 local `0.151.0` transcripts  | 1,197 `user.text`; 180 combined `agents_md.instructions` + `environments.environment_context`; 42 `unknown` hook prompts; 30 environment-only records; five combined plugin-recommendation + instructions + environment records; one `generic.turn_aborted`; one instructions-only record; zero missing user-role annotation arrays. |
| Wider `0.148.0`–`0.151.0` sample | Unannotated runtime shapes included 69 leading `codex_internal_context` records and one `recommended_plugins` record.                                                                                                                                                                                                                |

The current upstream checkout is newer than the installed `0.151.0` runtime. It adds or
changes classifications, including dynamic `<source>.internal_context`,
`model.base_instructions`, `compaction.summary`, `guardian.approved_action`,
`guardian.policy`, `generic.developer_instructions`, and
`persistent_mode.instructions`. These are source evidence for forward compatibility, not
claims that the installed binary already emits every value.

## Consumer implications

- Read `content` and `content_item_kinds` together by index before concatenating text.
- Treat only explicit current user-input kinds as positive evidence of human input.
- Treat known contextual, operational, instruction, generated, and extension annotations
  according to their producer and role, never as human merely because the Responses role
  is `user`.
- Treat `unknown`, absent metadata, malformed metadata, and length mismatch as
  unclassified. They fail closed as proof of human authorship.
- For unclassified legacy user-role text, use only upstream-grounded whole-fragment
  recognition. Plain residue outside a recognized runtime fragment remains candidate
  human input.
- Preserve unknown `ContentItemKind` strings for observability and compatibility. Do not
  reject or silently coerce them into a known kind.
- Do not use `turn_id`, `create_time`, message order, or XML-looking text alone as
  authorship evidence.

## Known gaps

- Rollout JSONL is not a published public API and can change independently of the CLI's
  documented command surface.
- Open-ended extension kinds prevent any literal inventory from being exhaustive.
- `0.152.0` exists upstream but was not the locally installed runtime in this verification.
- The local corpus establishes behavior on this machine; it does not prove every host,
  feature combination, or authentication mode emits identical records.
- Hook prompts currently depend on typed structural recognition because their response
  message is created without a provenance annotation.

## Sources

- https://developers.openai.com/codex/
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/protocol/src/models/item_metadata.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/protocol/src/models.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/context-fragments/src/annotated_content.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/context-fragments/src/fragment.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/core/src/session/mod.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/core/src/context/internal_model_context.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/protocol/src/items.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/thread-store/src/local/rollout_migration/rollback.rs
- https://github.com/openai/codex/blob/728cb12fe5794b0c3a8e776fb4994b1650b973a8/codex-rs/features/src/lib.rs
- https://github.com/openai/codex/pull/40174
- https://github.com/openai/codex/pull/40180
- https://github.com/openai/codex/pull/40196
