# Review Findings: conversation-projection-unification (Round 2)

## Verdict: APPROVE

## Summary

Second review pass against the post-fix state. The prior review (Round 1) found 3 Critical, 7 Important issues — all addressed in subsequent commits. The delivery now correctly implements the core behavioral goals: unified visibility projection through `WEB_POLICY`, web history/live SSE parity, input sanitization, and threaded/poller output cutover. All implementation-plan tasks are checked. Tests pass (3252 passed). No adapter files modified. No security issues.

Remaining findings are documentation accuracy, coupling concerns, test coverage gaps, and one potential edge-case bug. None block the core value delivery.

---

## Critical

None.

---

## Important

### I-1: Demo commands use invalid `ARGS` parameter

- **Location:** `demos/conversation-projection-unification/demo.md:28-31`
- **Issue:** Commands `make test ARGS="-k projection"` and `make test ARGS="-k test_web_parity"` do not work. The `test` target calls `./tools/test.sh` which does not accept or forward `ARGS`. The `ARGS` variable is only used by the `init` target. These commands run the full test suite, ignoring the `-k` filter. A user following the demo would get unexpected results.
- **Remediation:** Replace with direct pytest invocations: `pytest tests/unit/test_output_projection.py -k projection -v` and `pytest tests/unit/test_output_projection.py -k test_web_parity -v`.

### I-2: `str(block.get("text", ""))` produces `"None"` when key exists with `None` value

- **Location:** `teleclaude/output_projection/conversation_projector.py:186,204,216` and `teleclaude/output_projection/serializers.py:32`
- **Issue:** `dict.get("text", "")` returns `None` (not `""`) when the key is present with an explicit `None` value. Then `str(None)` produces the literal string `"None"`. The text-empty guard at line 187 (`if not text.strip(): continue`) does not catch `"None"` because `"None".strip()` is truthy. If a transcript entry contains `{"type": "text", "text": null}`, the user would see literal `"None"` in the chat.
- **Remediation:** Use `str(block.get("text") or "")` pattern, or `text if isinstance(text, str) else ""` to handle explicit `None` values.

### I-3: Schema/implementation mismatch — `ProjectedBlock` vs `UnifiedMessage`

- **Location:** `teleclaude/output_projection/models.py` vs `todos/conversation-projection-unification/schema.md`
- **Issue:** The schema defines message-level types (`UnifiedMessage` with `id`, `parts[]`, stable `call_id` on tools) while the implementation delivers block-level types (`ProjectedBlock` — one object per block, no message grouping, no `call_id`, no message `id`). The schema explicitly drops `file_index`/`entry_index` from the public stream, but `ProjectedBlock` and the API surface (`MessageDTO`) expose them. This is a structural divergence between the specified contract and the delivered code.
- **Remediation:** Document this as a known gap — phase 1 unified the filtering/projection; phase 2 would implement message-level grouping with `call_id` synthesis. The behavioral goals (web parity, tool suppression) are met without the schema types.

### I-4: Module docstring inaccuracy — `input_text`/`output_text` listed as assistant-only

- **Location:** `teleclaude/output_projection/conversation_projector.py:8`
- **Issue:** The contract doc says `assistant "text", "input_text", "output_text" (normalized to block_type="text")`, implying these types are only processed for assistant messages. However, the code at line 176 admits both `user` and `assistant` roles for block-based content. User entries with `input_text` blocks (which Claude transcripts produce at `transcript.py:993`) are also yielded as `block_type="text"`.
- **Remediation:** Rewrite to: `user and assistant "text", "input_text", "output_text" (normalized to block_type="text")`.

### I-5: `convert_projected_block` comment about "user text" is misleading

- **Location:** `teleclaude/api/transcript_converter.py:194`
- **Issue:** Comment says `# compaction, user text, unknown: no SSE event emitted`. But user text blocks have `block_type="text"` and ARE dispatched to `convert_text_block()` at line 186. The comment reads as if user text messages produce no SSE output, which is false — they produce `text-start`, `text-delta`, `text-end` events. The "user text" phrase in the comment is ambiguous and doesn't correspond to any actual block_type that falls through to the implicit else.
- **Remediation:** Change to: `# compaction and unknown block_types: no SSE event emitted`.

### I-6: Private function imports from transcript.py — coupling to internal API

- **Location:** `teleclaude/output_projection/conversation_projector.py:43-47`
- **Issue:** The projector imports 4 private (`_`-prefixed) functions from `transcript.py`: `_get_entries_for_agent`, `_is_compaction_entry`, `_is_user_tool_result_only_message`, `_parse_timestamp`. These are implementation details that could break on refactor. The codebase treats `_`-prefixed functions as module-private.
- **Remediation:** Consider making these public (remove `_` prefix) since they now have a cross-module consumer, or create a narrow public API in transcript.py for the projection layer.

### I-7: No Codex/Gemini-specific tests through the projection route

- **Location:** `tests/unit/test_output_projection.py`
- **Issue:** All test entry builders produce Claude-format entries. Codex `output_text`/`input_text` blocks and Gemini `thoughts[]`/`toolCalls[]` normalization paths are exercised only through `normalize_transcript_entry_message()` (tested elsewhere) but not through the new projection route end-to-end. SC#7 and SC#8 require correct assembly for these providers.
- **Remediation:** Add at least one test per provider using entries matching that provider's actual transcript format.

### I-8: `THREADED_CLEAN_POLICY` comment references function as source of truth (direction inverted)

- **Location:** `teleclaude/output_projection/models.py:37`
- **Issue:** Comment says `Matches the hardcoded behavior of render_clean_agent_output().` But `render_clean_agent_output()` now USES `THREADED_CLEAN_POLICY` (at `transcript.py:546`). The policy IS the source of truth, not a mirror. This creates a stale reference that will become increasingly confusing.
- **Remediation:** Rewrite to: `Threaded clean policy: thinking and tool invocations visible, results hidden. Used by render_clean_agent_output() for threaded output formatting.`

---

## Suggestions

### S-1: Import inside polling loop should be at function level

- **Location:** `teleclaude/core/polling_coordinator.py:884`
- **Issue:** Deferred import placed inside `async for` loop body. No circular dependency justifies this. Standard pattern in codebase is function-body level.

### S-2: `TerminalLiveProjection` wraps string with no behavior

- **Location:** `teleclaude/output_projection/models.py:69-78` and `terminal_live_projector.py`
- **Issue:** `TerminalLiveProjection` is a dataclass wrapping a single `str` field with no validation, transformation, or invariant enforcement. `project_terminal_live()` does `return TerminalLiveProjection(output=output)`. Consider `NewType("TerminalLiveOutput", str)` for zero-overhead type distinction, or accept that this is an intentional extension point.

### S-3: `serializers.py` docstring describes the past, not the present

- **Location:** `teleclaude/output_projection/serializers.py:21-22`
- **Issue:** "Replaces the per-consumer text extraction logic that was scattered across extract_messages_from_chain() and convert_entry()" describes what was replaced. Comments describe the present per naming policy.

### S-4: `api_server.py` comment references "the previous"

- **Location:** `teleclaude/api_server.py:1226-1227`
- **Issue:** "same semantics as the previous extract_messages_from_chain() boolean flags" describes history.

### S-5: `extract_structured_messages()` not marked deprecated

- **Location:** `teleclaude/utils/transcript.py:2094`
- **Issue:** `extract_messages_from_chain()` has the deprecation notice (from prior review), but `extract_structured_messages()` which it wraps has independent logic and no deprecation annotation.

### S-6: `to_structured_message()` returns empty text for unknown block types without logging

- **Location:** `teleclaude/output_projection/serializers.py:43-44`
- **Issue:** The `else` branch produces `text=""` silently. Future block types would produce ghost messages.

### S-7: `visible_tool_names` only affects `tool_use`, not `tool_result` — potential surprise

- **Location:** `teleclaude/output_projection/conversation_projector.py:215-217` vs `227-236`
- **Issue:** Allowlisting a tool name makes its `tool_use` block visible, but not its corresponding `tool_result`. A widget tool that should show both invocation and result would need `include_tool_results=True`, which enables ALL tool results.

### S-8: `block_type` and `role` on `ProjectedBlock` should use `Literal[...]`

- **Location:** `teleclaude/output_projection/models.py:61,63`
- **Issue:** `str` types provide no static analysis value. `Literal["text", "thinking", "tool_use", "tool_result", "compaction"]` and `Literal["assistant", "user", "system"]` would catch typos at type-check time.

### S-9: SSE stream continues after message delivery failure

- **Location:** `teleclaude/api/streaming.py:188-196`
- **Issue:** After `process_message` fails, an "error" status is yielded but the stream continues into history replay. The user sees error + content, which is contradictory. This is pre-existing behavior, not introduced by this branch.

---

## Scope Verification

- **All 16 success criteria in `requirements.md`**: Core behavioral criteria met (SC#1-10, SC#13-14). SC#3-5 (sanitization) fixed in prior review round. SC#11-12 (legacy helpers) partially met — render functions are wrappers, `extract_messages_from_chain` deprecated, search/checkpoint helpers deferred with documented handoff. No gold-plating.
- No adapter files modified.
- Mirror/search adoption correctly deferred with documented handoff point (`search.py:138-142`).

## Paradigm-fit

- Follows established data flow patterns: new package between core data and consumers.
- Reuses existing normalization infrastructure.
- No copy-paste duplication detected.
- Frozen dataclasses, module-level constants, iterator-based projection all consistent with codebase conventions.

## Security

- No hardcoded credentials, no PII in logs, no injection vectors, authorization checks preserved.

## Demo

- `demos/conversation-projection-unification/demo.md` has executable bash blocks.
- Commands 3-7 are valid. Commands 1-2 use invalid `ARGS` parameter (see I-1).
- Scenarios accurately describe implemented features.

## Why No Critical Issues

1. **Paradigm fit verified**: New package follows existing data flow patterns (normalization → projection → serialization). No copy-paste, no bypassed data layer.
2. **Requirements validated**: All 16 success criteria traced — core behavioral criteria met, sanitization implemented, legacy helpers appropriately deprecated/deferred.
3. **Security reviewed**: No credential exposure, log leakage, injection, or auth bypass in diff.
4. **Prior critical fixes confirmed**: All 3 Critical and 7 Important findings from Round 1 addressed in commits `96f2b79`, `663a9bc`, `bce9a72`, `4fcb0b5`, `3956f68`.

## Prior Review Fixes (Round 1)

| Finding | Fix | Commit |
|---------|-----|--------|
| C-1: Input sanitization not implemented | Added `_is_internal_user_text()` sanitizer | `96f2b79`, `663a9bc` |
| C-2: False docstring in `transcript_converter.py` | Revised module docstring | `4fcb0b5` |
| C-3: `THREADED_FULL_POLICY` duplicate | Removed | `3956f68` |
| I-1: Module-level contract doc too thin | Expanded docstring | `96f2b79` |
| I-2: Old helpers not deprecated | Added deprecation notice | `bce9a72` |
| I-3: System-role block entries coerced | Added guard | `96f2b79` |
| I-4: Type annotation mismatch | Changed to `dict[str, object]` | `3956f68` |
| I-5: `project_conversation_chain()` untested | Added chain tests | `663a9bc` |
| I-6: User text messages path untested | Added user text test | `663a9bc` |
| I-7: No logging in projector | Added debug logging | `96f2b79` |
