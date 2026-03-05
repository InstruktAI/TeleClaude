# Implementation Plan: context-delivery-dedup

## Overview

Two parallel workstreams: (1) change `build_context_output()` to list dependency IDs
in the header instead of expanding their content, and (2) trim the global AGENTS.md
baseline by removing three large sections from their source artifacts. Both changes go
through `telec sync` for the generated output.

## Phase 1: Core Context Delivery Change

### Task 1.1: Modify output rendering in `build_context_output()`

**File(s):** `teleclaude/context_selector.py` (lines 731-768)

- [x] Change the output loop to only emit content for explicitly requested snippet IDs
      (those in `selected_ids`), not for resolved dependencies.
- [x] Change header line from `# Auto-included (required by the above): {dep_ids}`
      to `# Required reads (not loaded): {dep_ids}`.
- [x] Keep `_resolve_requires()` call intact — it still computes the dep tree to get
      the ID list for the header.
- [x] Adjust the `for snippet in resolved` loop: skip content emission for snippets
      whose `snippet_id` is not in `requested_set`. Only the ID appears in the header.

### Task 1.2: Verify CLI handler needs no changes

**File(s):** `teleclaude/cli/telec.py` (lines 1611-1645)

- [x] Confirm `_handle_docs_get()` passes through to `build_context_output()` without
      output formatting of its own. No changes expected — verify only.

---

## Phase 2: AGENTS.md Trimming

### Task 2.1: Remove Agent Direct Conversation from baseline

**File(s):** `docs/global/baseline.md`

- [x] Remove the `@...agent-direct-conversation.md` reference line from `baseline.md`.
- [x] Verify the snippet still exists in the doc index and is loadable via
      `telec docs get general/procedure/agent-direct-conversation`.

### Task 2.2: Trim Telec CLI spec — remove sessions expanded sections

**File(s):** `docs/global/general/spec/tools/telec-cli.md`

- [x] Remove the `<!-- @exec: telec sessions -h -->` directive and its `### telec sessions` heading.
- [x] Remove the `<!-- @exec: telec sessions send -h -->` directive and its
      `### telec sessions send` heading.
- [x] Keep the `### telec docs` section with its `<!-- @exec: telec docs -h -->` directive.
- [x] Keep the `## CLI surface` section with `<!-- @exec: telec -h -->` (the overview block).

### Task 2.3: Replace baseline index with one-liner

**File(s):** `docs/global/baseline-progressive.md`

- [x] Replace the 16 `@` reference lines with a single instruction line:
      `Run telec docs index --baseline-only before any task where context might be needed.`
      This makes the baseline index discoverable at runtime without pre-loading 2.4k of IDs.

Note: The baseline index block in the generated `AGENTS.md` will no longer appear inline.
Agents discover available snippets via `telec docs index` instead.

---

## Phase 3: Doc & Policy Updates

### Task 3.1: Update Context Retrieval policy snippet

**File(s):** Doc snippet `general/policy/context-retrieval` (source file)

- [ ] Update the two-phase flow description to reflect the new behavior: "index → get
      snippets → get missing deps listed in the Required reads header."
- [ ] Remove any mention of automatic dependency expansion.

### Task 3.2: Update telec-cli spec description if needed

**File(s):** `docs/global/general/spec/tools/telec-cli.md`

- [ ] Update the `telec docs get` notes section if it mentions auto-inclusion behavior.

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Update `tests/integration/test_context_selector_e2e.py` if it asserts on
      "Auto-included" header format (currently only asserts on "PHASE 2" — likely no change).
- [x] Add a test that verifies: when snippet-a requires snippet-c, calling
      `build_context_output(snippet_ids=["snippet-a"])` returns snippet-a content
      and a `# Required reads (not loaded): snippet-c` header (no snippet-c content).
- [x] Add a test that verifies: when explicitly requesting snippet-c, its content IS included.
- [x] Run `make test` and `make lint`.

### Task 4.2: Regenerate and verify

- [ ] Run `telec sync` to regenerate AGENTS.md and all distribution artifacts.
- [ ] Verify `~/.claude/CLAUDE.md` size is under 28k chars.
- [ ] Verify Agent Direct Conversation is NOT in the generated CLAUDE.md.
- [ ] Verify `telec sessions` and `telec sessions send` expanded help is NOT in
      the generated CLAUDE.md.
- [ ] Verify the baseline index block is replaced with the one-liner.
- [ ] Verify `telec docs get general/procedure/agent-direct-conversation` still works.

### Task 4.3: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain
