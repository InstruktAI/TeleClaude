# Unified Event Stream Schema

This file defines the assembled transcript-derived event stream that clients consume.

It is intentionally narrow.

The parser may preserve richer provider-specific detail internally, but the assembled stream only includes what clients are expected to use.

## Design Intent

The assembly stage should:

- normalize Claude, Codex, and Gemini transcript files
- strip TeleClaude-injected user-input artifacts
- assemble one stable client-facing stream shape
- expose only the content clients are interested in

The assembly stage should not:

- expose transcript provenance
- expose parser internals
- expose provider quirks
- expose hidden TeleClaude checkpoint/control input
- make presentation choices for clients

## Single Entry Point Rule

There must be exactly one semantic entry point for transcript-derived output.

All transcript-derived callers must use that one entry point.

No other code may:

- semantically parse transcript source files directly
- classify raw transcript entries independently
- assemble its own transcript message model from raw files

Existing helper functions that currently do this must become:

- thin wrappers over the unified entry point, or
- deleted

There must not be multiple semantic paths under the hood.

## Public Stream Shape

```ts
type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

type UnifiedEventStream = {
  schema_version: 1;
  messages: UnifiedMessage[];
};

type UnifiedMessage = {
  id: string;
  role: "user" | "assistant";
  timestamp?: string | null;
  parts: UnifiedPart[];
};

type UnifiedPart =
  | TextPart
  | ThinkingPart
  | ToolCallPart
  | ToolResultPart;

type TextPart = {
  type: "text";
  text: string;
};

type ThinkingPart = {
  type: "thinking";
  text: string;
};

type ToolCallPart = {
  type: "tool_call";
  call_id: string;
  name: string;
  input: JsonValue;
};

type ToolResultPart = {
  type: "tool_result";
  call_id: string;
  output: JsonValue;
  is_error?: boolean | null;
};
```

## What Is Included

Only these semantic leaves are assembled into the public stream:

- user text
- assistant text
- assistant thinking
- assistant tool calls
- assistant tool results

## What Is Explicitly Dropped

These do not belong in the assembled client stream:

- transcript file paths
- file indices
- entry indices
- raw entry types
- raw payload/block types
- raw provider ids
- provider call ids
- source format labels
- turn ids
- sequence counters
- text subtype metadata
- thought origin metadata
- thought labels
- tool display names separate from `name`
- model name
- token usage
- compaction markers
- unknown raw blocks
- system-role transcript messages

Those may exist transiently inside the implementation of the unified entry point, but they are not assembled into the public stream and are not a caller-facing contract.

## Input Sanitization Rules

The assembly stage must inspect user-originated transcript content before it is exposed.

### Rule 1: Drop TeleClaude system-prefixed user input

If a user text payload begins with the canonical TeleClaude system prefix after trimming leading whitespace, it must be removed from the assembled stream.

Canonical prefix from code:

- `TELECLAUDE_SYSTEM_PREFIX = "[TeleClaude"`

Examples that must be stripped:

- `[TeleClaude Checkpoint] - Context-aware checkpoint`
- `[TeleClaude Direct Conversation]`
- `[TeleClaude Worker Stopped]`

### Rule 2: Drop TeleClaude wrapper payloads in user text blocks

The assembly stage must drop user-text wrapper payloads that are internal control artifacts rather than conversation.

Known cases in the current codebase:

- `<task-notification> ... </task-notification>`
- pure `<system-reminder> ... </system-reminder>` payloads

### Rule 3: Drop empty user messages after sanitization

If all user parts are removed by sanitization, the assembled user message must not be emitted.

## Assembly Semantics

### Message ids

`UnifiedMessage.id` must be stable for replay/history/live parity.

Recommended construction:

```txt
{file_index}:{entry_index}:{role}
```

If one raw transcript entry yields multiple assistant messages during normalization, append a deterministic suffix:

```txt
{file_index}:{entry_index}:{role}:{n}
```

### Tool correlation

`call_id` must always exist.

Rules:

- use provider-native call ids when present
- otherwise synthesize a deterministic id from message/block position

### Role correction

Claude writes tool results as user-role transcript content.
Those are not real user messages.

Assembly rule:

- when a user transcript message contains only `tool_result` blocks, assemble it as `role: "assistant"`

### Ordering

History and live assembly must emit the same message and part order for the same transcript chain.

## Provider Mapping

### Claude

Assemble:

- user string content -> user `text`
- assistant `text` -> assistant `text`
- assistant `thinking` -> assistant `thinking`
- assistant `tool_use` -> assistant `tool_call`
- user `tool_result`-only message -> assistant `tool_result`

Drop:

- system compaction entries from the public stream
- TeleClaude-prefixed injected user text

### Codex

Assemble:

- `response_item.payload.type == "message"` user `input_text` -> user `text`
- `response_item.payload.type == "message"` assistant `output_text` -> assistant `text`
- `response_item.payload.type == "reasoning"` -> assistant `thinking`
- `response_item.payload.type == "function_call"` -> assistant `tool_call`
- `response_item.payload.type == "function_call_output"` -> assistant `tool_result`
- `response_item.payload.type == "custom_tool_call"` -> assistant `tool_call` plus `tool_result` when output/error exists

Drop:

- TeleClaude-prefixed injected user text

### Gemini

Assemble:

- `type == "user"` `content` -> user `text`
- `type == "gemini"` `content` -> assistant `text`
- each `thoughts[]` item -> assistant `thinking`
- each `toolCalls[]` item -> assistant `tool_call`
- each nested tool result item -> assistant `tool_result`

Drop:

- TeleClaude-prefixed injected user text if it appears in user messages

## Required Code Documentation

The implementation must include a rich module-level documentation block in the assembly/parser code that states:

1. what the assembled stream includes
2. what it intentionally drops
3. what user-input sanitization rules are applied
4. why the public stream is narrower than the private normalization logic

That code doc is part of the contract, not optional commentary.

## Required Architecture Documentation

The implementation must include a project architecture document describing:

- the unified event stream schema
- the sanitization rules
- the exact fields/parts that are assembled
- the exact data intentionally dropped from assembly
- which consumers read the unified stream

The goal is that future work can reintroduce dropped data consciously, not accidentally.
