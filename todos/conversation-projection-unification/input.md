# Input: conversation-projection-unification

Unify transcript-derived output behind one narrow assembled event stream for clients.

## Problem

The codebase currently has multiple inconsistent transcript consumers:

1. web history uses lossy `StructuredMessage` rows
2. web live replays raw transcript entries through `convert_entry()`
3. threaded transcript output reparses transcript content with custom rules
4. frontend history assembly only understands `text` and `thinking`
5. internal TeleClaude-injected user messages still leak through some transcript consumers

This produces two classes of bugs:

- different consumers see different interpretations of the same transcript truth
- internal TeleClaude input artifacts surface in user-visible history/live output

## Required Outcome

Build one transcript parser + assembly path that outputs the public schema in [schema.md](./schema.md).

That public stream is intentionally narrow:

- user text
- assistant text
- assistant thinking
- assistant tool calls
- assistant tool results

Everything else is internal implementation detail and is not a caller-facing contract.

## Key Requirement

This is not only a shape-construction task.

The assembly step must also sanitize user transcript input and strip TeleClaude-injected artifacts before they become part of the public event stream.

The canonical stripping anchor is the shared prefix from code:

- `TELECLAUDE_SYSTEM_PREFIX = "[TeleClaude"`

## Scope Boundary

This todo is about transcript-derived client output unification.

It is not:

- a tmux polling redesign
- a control-plane activity redesign
- an adapter transport rewrite
- a generic “show everything” transcript dump

Clients should receive one clean assembled stream and decide how to present it.

## Single Entry Point Requirement

This todo must end with exactly one transcript-derived semantic entry point.

No caller is allowed to semantically read transcript source files except through that unified entry point.

That means the current independent transcript interpreters must stop being architecture owners.

## Concrete Code Paths To Replace

### Backend transcript assembly

- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L170)
- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L947)
- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L2024)
- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L2065)
- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L2224)

### Web history/live

- [api_server.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/api_server.py#L1182)
- [streaming.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/api/streaming.py#L146)
- [transcript_converter.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/api/transcript_converter.py#L1)
- [MyRuntimeProvider.tsx](/Users/Morriz/Workspace/InstruktAI/TeleClaude/frontend/components/assistant/MyRuntimeProvider.tsx#L30)
- [types.ts](/Users/Morriz/Workspace/InstruktAI/TeleClaude/frontend/lib/api/types.ts#L159)

### Threaded transcript consumer

- [agent_coordinator.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/core/agent_coordinator.py#L1234)
- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L491)
- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L1069)

### Related downstream consumers

- [transcript.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/utils/transcript.py#L1519)
- mirror/search consumers that currently depend on their own extraction assumptions

## Non-Negotiable Invariants

1. One assembled client stream schema for transcript-derived content.
2. TeleClaude-injected user input is stripped before public assembly.
3. Clients get thinking and tool calls/results, not only final text.
4. Public assembly stays narrow on purpose.
5. Dropped fields/data are documented explicitly in code and architecture docs.
6. No transcript-derived caller bypasses the unified entry point.
