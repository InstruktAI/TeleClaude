# Requirements: conversation-projection-unification

## Goal

Replace the current mix of lossy extraction, raw entry replay, and consumer-specific transcript interpretation with one narrow assembled event stream defined in [schema.md](./schema.md).

## Scope

### In scope

- One transcript-derived public assembly schema:
  - `UnifiedEventStream`
  - `UnifiedMessage`
  - `UnifiedPart`
- Full transcript normalization for Claude, Codex, and Gemini sufficient to assemble:
  - `text`
  - `thinking`
  - `tool_call`
  - `tool_result`
- Input sanitization rules applied before public assembly.
- Replacing the current history/live/threaded transcript consumers with serializers/readers over the same assembled stream.
- Explicit documentation of:
  - what is assembled
  - what is stripped
  - what is intentionally dropped
- Regression coverage for history/live parity and TeleClaude-input stripping.

### Out of scope

- Exposing parser provenance fields in the public event stream.
- Exposing compaction/system transcript entries in the public event stream.
- Tmux polling mechanics.
- Control-plane activity event schema.
- Adapter transport mechanics.
- Generic raw transcript dump endpoints.

## Success Criteria

- [ ] One canonical transcript assembly path produces the schema in [schema.md](./schema.md) for Claude, Codex, and Gemini transcripts.
- [ ] The public stream contains only:
  - user `text`
  - assistant `text`
  - assistant `thinking`
  - assistant `tool_call`
  - assistant `tool_result`
- [ ] User transcript payloads starting with `TELECLAUDE_SYSTEM_PREFIX` are stripped before public assembly.
- [ ] Known internal wrapper payloads are stripped before public assembly:
  - `<task-notification> ... </task-notification>`
  - pure `<system-reminder> ... </system-reminder>`
- [ ] User messages emptied by sanitization are dropped from the public stream.
- [ ] Claude user-role `tool_result` transcript messages assemble as assistant `tool_result` output.
- [ ] Codex `reasoning`, `function_call`, `function_call_output`, and `custom_tool_call` transcript payloads assemble correctly into the public schema.
- [ ] Gemini `thoughts[]` and `toolCalls[]` assemble correctly into the public schema.
- [ ] Web history and web live are backed by the same assembled stream and therefore expose the same semantics.
- [ ] Threaded transcript consumers serialize from the same assembled stream rather than reparsing raw transcript content.
- [ ] No transcript-derived caller semantically reads transcript source files outside the unified entry point.
- [ ] Existing transcript helper entry points become wrappers over the unified entry point or are deleted:
  - `extract_structured_messages()`
  - `extract_messages_from_chain()`
  - `collect_transcript_messages()`
  - `extract_tool_calls_current_turn()`
  - `render_agent_output()`
  - `render_clean_agent_output()`
  - `convert_entry()`
- [ ] The code contains a rich module-level contract doc explaining:
  - included parts
  - stripped user-input rules
  - intentionally dropped data
- [ ] Architecture docs contain a matching unified-event-stream contract with the same drop list.

## Public Assembly Constraints

- Public assembly must remain narrow.
- Public assembly must not expose:
  - transcript paths
  - file indices
  - entry indices
  - raw entry/payload types
  - provider ids
  - provider call ids
  - model names
  - token usage
  - compaction markers
  - unknown/raw block payloads
  - system-role transcript entries
- Public assembly must always provide a stable `call_id` for tool calls/results.
- Public assembly must not flatten tool calls/results into display strings.
- Public assembly must not rely on frontend-specific filtering to hide TeleClaude system input.
- Transcript source files must have one semantic reader path only.

## Current Confirmed Gaps

1. [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L2065) currently collapses transcript data into `StructuredMessage(role, type, text, ...)`, which is too lossy for the desired public stream.
2. [api_server.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/api_server.py#L1182) still exposes history through that lossy model.
3. [streaming.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/api/streaming.py#L146) and [transcript_converter.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/api/transcript_converter.py#L159) still serialize raw transcript entries directly.
4. [MyRuntimeProvider.tsx](/Users/Morriz/Workspace/InstruktAI/TeleClaude/frontend/components/assistant/MyRuntimeProvider.tsx#L34) only rebuilds history from `text` and `thinking`, ignoring tool parts.
5. TeleClaude checkpoint/control input is known in code via [constants.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/constants.py#L100), but the transcript public assembly path does not own stripping it.

## Affected Consumers

These consumers must be updated to read the unified assembled stream:

- `GET /sessions/{session_id}/messages`
- `/api/chat/stream`
- frontend history loader
- frontend live thread rendering
- threaded transcript output generation
- transcript-backed mirror/search extraction
- transcript-backed summarizer/text-collector helpers

## Risks

- Threaded output currently formats from transcript helpers with bespoke behavior. Mitigation: move formatting onto the assembled stream, keep formatting as a consumer concern.
- Different agents encode tool activity very differently. Mitigation: normalize privately, assemble narrowly.
- Overexposing parser internals would recreate the current problem. Mitigation: keep the drop list explicit in code and docs.
