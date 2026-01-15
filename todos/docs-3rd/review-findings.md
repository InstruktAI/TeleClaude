# Code Review: docs-3rd

**Reviewed**: 2026-01-15
**Reviewer**: Codex

## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: 0
- Silent deferrals found: no

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
| --- | --- | --- | --- | --- |
| `docs/3rd/` exists with a clear index file. | `docs/3rd/index.md:1` (contains stale entry) | N/A (static artifact) | NO TEST (static artifact) | ❌ |
| Research workflow creates new vendor docs without manual formatting. | `.claude/commands/research-docs.md:1`, `scripts/research_docs.py:56` | `.claude/commands/research-docs.md:1` → `scripts/research_docs.py:56` → `scripts/research_docs.py:9` | `tests/integration/test_research_docs_workflow.py:test_end_to_end_workflow` | ✅ |
| Index is updated on every new or refreshed doc. | `scripts/research_docs.py:82` | `.claude/commands/research-docs.md:1` → `scripts/research_docs.py:56` → `scripts/research_docs.py:9` | `tests/unit/test_research_docs.py:test_update_index_new` | ✅ |
| Docs are concise, source‑linked, and usable for follow‑on work. | NOT FOUND (`docs/3rd/codex-cli-hooks.md` missing standard header/content) | `.claude/commands/research-docs.md:1` → `scripts/research_docs.py:56` | NO TEST | ❌ |

**Verification notes:**
- `docs/3rd/index.md` lists `test-doc.md`, but that file is missing from `docs/3rd/`, so the index is inaccurate.
- `docs/3rd/codex-cli-hooks.md` does not include the standardized Source/Last Updated header or any content.
- The integration test exercises the script only, not the full “short prompt → research → summary → index” flow.

### Integration Test Check
- Main flow integration test exists: no
- Test file: `tests/integration/test_research_docs_workflow.py`
- Coverage: Runs `scripts/research_docs.py` and asserts doc + index output
- Quality: Not isolated (writes to `docs/3rd/index.md` and leaves changes)

### Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| O1: Provide a reusable skill or command that performs focused research and writes concise markdown into `docs/3rd/`. | ✅ | `.claude/commands/research-docs.md` exists and points to the script. |
| O2: Maintain a single index file listing vendor docs, their purpose, and last update time. | ❌ | Index includes a test entry pointing to a missing file; not all entries correspond to real docs. |
| O3: Minimal user input, workflow runs from a short prompt and does the rest autonomously. | ❌ | Command still requires manual parameter selection and manual summary content. |
| O4: Usable by Context Assembler. | ❌ | Missing metadata/content in `codex-cli-hooks.md` and stale index entry reduce reliability. |

## Critical Issues (must fix)

- [docs] `docs/3rd/index.md:27` - Index references `test-doc.md`, but the file does not exist, making the index inaccurate and violating O2.
  - Suggested fix: remove the test entry or add the corresponding doc; ensure tests do not leave index entries behind.
- [docs] `docs/3rd/codex-cli-hooks.md:1` - Doc is missing standardized header (Source/Last Updated) and any content, so it is not source‑linked or usable.
  - Suggested fix: populate the doc with the standard header and a concise summary, or remove the index entry until content exists.

## Important Issues (should fix)

- [tests] `tests/integration/test_research_docs_workflow.py:52` - Integration test writes to `docs/3rd/index.md` and leaves the test entry, violating test isolation and causing index drift.
  - Suggested fix: run the script against a temp directory or back up/restore the index file; alternatively, add an output-dir argument for tests.
- [code] `.claude/commands/research-docs.md:7` - Minimal‑input requirement (O3) is not met; the workflow still requires manual values for title/filename/source/purpose/content.
  - Suggested fix: add a wrapper command/script that takes a brief and automates search, fetch, summarization, and indexing.

## Suggestions (nice to have)

- [tests] `tests/integration/test_research_docs_workflow.py:17` - Remove unused `self.index_path`/`self.doc_path` or use them to drive an isolated test directory.

## Strengths

- `scripts/research_docs.py` standardizes headers and keeps index entries consistent.
- Purpose metadata is captured in the index, improving discoverability.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Fix the stale index entry (`test-doc.md`) and ensure index only lists real docs.
2. Populate `docs/3rd/codex-cli-hooks.md` with source-linked content and standard headers.
3. Make the integration test isolated so it does not mutate tracked docs.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Stale index entry (test-doc.md) | Removed test entry from docs/3rd/index.md | e746367 |
| Empty codex-cli-hooks.md without valid source | Removed codex-cli-hooks.md and index entry | 12fc445 |
| Integration test mutates tracked docs | Added --output-dir parameter to script and updated test to use isolated directory | 6c9d240 |

**Test Results:**
- Unit tests: 827 passed
- Integration tests: 59 passed
- All lint checks: PASSED
