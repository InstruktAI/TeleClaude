# Implementation Plan: Context Assembler AI

## Phase 1: Index generation

- [ ] Traverse markdown references from each index root and produce `index.json`.
- [ ] Include flattened file paths and tag arrays per file.
- [ ] Each project exposes a single hook that passes its `index.json` path to the receiver.
- [ ] Determine actual hook execution order per CLI, then enforce layering so global context is applied before project context.

## Phase 2: Selection inputs

- [ ] Use the existing documentation index as the candidate list.
- [ ] Define the selection prompt: “Given this user message, choose the minimal set of docs that change behavior.”
- [ ] Selection output target: JSON array of file paths (primary). Parser must also accept `{ "result": [ ... ] }` as a tolerant fallback.
- [ ] Deduplicate selected paths and skip anything already injected.
- [ ] Merge global index with project index using the path from the project hook.

## Phase 3: Selector runtime

- [ ] Implement a selector client that calls the fastest OpenAI API model.
- [ ] Keep the interface model‑agnostic for future local LLM swap‑in.
- [ ] Enforce a hard timeout and max tokens to keep selection fast.
- [ ] On selector failure/timeout, skip injection and continue.

## Phase 4: Injection engine

- [ ] Track already‑injected docs per session.
- [ ] Inject only new docs (delta‑only).
- [ ] Use `hookSpecificOutput.additionalContext` for injection where supported.
- [ ] Claude: inject on `UserPromptSubmit`.
- [ ] Gemini: use `BeforeAgent` with `hookSpecificOutput.additionalContext` and add a 10‑second time‑window rate‑limit (allow repeat injection after the window, avoid rapid repeats).
- [ ] Implement Codex TMUX injection path.
- [ ] Persist injected doc paths per session as newline‑delimited list in the DB.
- [ ] Add `context_paths` column to the sessions table and migrate safely.
- [ ] Rate‑limit state lives in memory (ephemeral, per active session).
- [ ] Injection payloads: Claude/Gemini JSON with `hookSpecificOutput.additionalContext` string; Codex uses TMUX injection of system‑prompt append.

## Phase 5: Validation

- [ ] Simulate a multi‑turn session and confirm incremental doc injection.
- [ ] Verify no re‑injection of already included docs.
- [ ] Measure selection latency under typical inputs.
