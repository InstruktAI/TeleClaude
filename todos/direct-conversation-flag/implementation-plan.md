# Implementation Plan: direct-conversation-flag

## Overview

A surgical change: add one boolean parameter to two MCP tool handlers and guard five `_register_listener_if_present` call sites. The MCP dispatch layer and model need to pass the flag through. Default `False` preserves all existing behavior.

---

## Phase 1: Handler Changes

### Task 1.1: Add `direct` parameter to `teleclaude__send_message`

**File(s):** `teleclaude/mcp/handlers.py`

- [ ] Add `direct: bool = False` to `teleclaude__send_message` signature (L521)
- [ ] Wrap `_register_listener_if_present` call at L530 in `if not direct:`

### Task 1.2: Add `direct` parameter to `teleclaude__start_session`

**File(s):** `teleclaude/mcp/handlers.py`

- [ ] Add `direct: bool = False` to `teleclaude__start_session` signature (L297)
- [ ] Wrap `_register_listener_if_present` call at L361 in `if not direct:`
- [ ] Wrap `_register_listener_if_present` call at L643 in `if not direct:` (remote session path)
- [ ] Wrap `_register_listener_if_present` call at L701 in `if not direct:` (remote fallback path)
- [ ] Wrap `_register_listener_if_present` call at L720 in `if not direct:` (if applicable to start_session flow)

---

## Phase 2: MCP Schema and Dispatch

### Task 2.1: Update `StartSessionArgs` model

**File(s):** `teleclaude/core/models.py`

- [ ] Add `direct: bool = False` field to `StartSessionArgs` (L703)

### Task 2.2: Update MCP dispatch layer

**File(s):** `teleclaude/mcp_server.py`

- [ ] Extract `direct` from arguments in `_handle_send_message` (L443) and pass to handler
- [ ] Extract `direct` from arguments in `_handle_start_session` (L439) and pass to handler
- [ ] Add `direct` to tool schema definitions with description: "When true, skip automatic notification subscription. Use for peer-to-peer agent communication."

---

## Phase 3: Validation

### Task 3.1: Tests

- [ ] Test `send_message` with `direct=true` — verify `_register_listener_if_present` is NOT called
- [ ] Test `send_message` with `direct=false` (default) — verify `_register_listener_if_present` IS called
- [ ] Test `start_session` with `direct=true` — verify no subscription created
- [ ] Test `start_session` with `direct=false` (default) — verify subscription created
- [ ] Run `make test`

### Task 3.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm all implementation tasks are marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
