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
| `docs/3rd/` exists with a clear index file. | `docs/3rd/index.md:1` | N/A (static artifact) | NO TEST (static artifact) | ✅ |
| Research workflow creates new vendor docs without manual formatting. | `.claude/commands/research-docs.md:1`, `scripts/research_docs.py:56` | `.claude/commands/research-docs.md:1` -> `scripts/research_docs.py:56` -> `scripts/research_docs.py:10` | NO TEST | ❌ |
| Index is updated on every new or refreshed doc. | `scripts/research_docs.py:81` | `.claude/commands/research-docs.md:1` -> `scripts/research_docs.py:56` -> `scripts/research_docs.py:10` | `tests/unit/test_research_docs.py:test_update_index_new` | ✅ |
| Docs are concise, source-linked, and usable for follow-on work. | `docs/3rd/openai-realtime-api.md:1` | `.claude/commands/research-docs.md:1` -> `scripts/research_docs.py:56` | NO TEST | ✅ |

**Verification notes:**
- The research command frontmatter is malformed and references undefined tools, so the end-to-end workflow is not runnable as written.
- The index does not include a purpose field, so the requirement for purpose metadata is not met.

### Integration Test Check
- Main flow integration test exists: no
- Test file: N/A
- Coverage: N/A
- Quality: N/A

### Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| O1: Provide a reusable skill or command that performs focused research and writes concise markdown into `docs/3rd/`. | ❌ | `.claude/commands/research-docs.md` frontmatter is malformed and references undefined tools. |
| O2: Maintain a single index file listing vendor docs, their purpose, and last update time. | ❌ | `docs/3rd/index.md` and `scripts/research_docs.py` do not capture purpose. |
| O3: Minimal user input, workflow runs from a short prompt and does the rest autonomously. | ❌ | Command is not runnable as written; manual script invocation required. |
| O4: Usable by Context Assembler. | ⚠️ | Missing purpose metadata makes selection ambiguous. |

## Critical Issues (must fix)

- [code] `.claude/commands/research-docs.md:1` - Frontmatter is malformed, so the command is likely not parsed by the command runner.
  - Suggested fix: use proper YAML frontmatter with a closing `---` line.
- [code] `.claude/commands/research-docs.md:10` - The workflow calls `google_web_search` and `web_fetch`, which are not referenced anywhere in this repo and likely do not exist.
  - Suggested fix: replace with the actual tool names used in this environment and document them in the command.
- [docs] `docs/3rd/index.md:3` - Index entries do not include a purpose field, violating O2 and making Context Assembler selection ambiguous.
  - Suggested fix: add a `- Purpose:` line per entry and update `scripts/research_docs.py` to accept and write a purpose value.

## Important Issues (should fix)

- [tests] `tests/unit/test_research_docs.py:1` - No integration test exercises the end-to-end workflow of writing a doc and updating the index.
  - Suggested fix: add an integration test that runs `scripts/research_docs.py` against a temp directory and asserts both the doc file and index entry content.
- [code] `scripts/research_docs.py:7` - Unused import and missing return type annotations violate lint and typing directives.
  - Suggested fix: remove unused imports and add explicit return types for `update_index` and `main`.
- [tests] `tests/unit/test_research_docs.py:5` - Unused imports and unused variables will fail lint.
  - Suggested fix: remove unused imports and dead setup comments or variables.

## Suggestions (nice to have)

- [docs] `docs/3rd/index.md:13` - Add a blank line between entries to keep the index easy to scan.

## Strengths

- Standardized doc headers in `scripts/research_docs.py` make new entries consistent.
- Example doc entry shows the intended source-linked format.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Fix the research command frontmatter and tool references so the workflow is runnable.
2. Add purpose metadata to index entries and update the script to maintain it.
3. Add an end-to-end test for the research workflow.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Malformed YAML frontmatter in research-docs.md | Fixed frontmatter by adding newline before closing --- | 605ba84 |
| Undefined tool references (google_web_search, web_fetch) | Replaced with WebSearch and WebFetch | 605ba84 |
| Missing purpose field in index entries | Added --purpose parameter to script, updated update_index() function, manually added purpose to all existing index entries, updated command documentation | 161caed |
| Missing return type annotations in research_docs.py | Added return type annotations to update_index() and main() | 161caed |
| Unused imports in test_research_docs.py | Removed unused imports (shutil, datetime, StringIO, main), moved MagicMock to top-level import | da56358 |
| Missing purpose parameter in test calls | Updated test_update_index_new and test_update_index_existing to include purpose parameter and assertions | da56358 |
| No integration test for end-to-end workflow | Created test_research_docs_workflow.py integration test that verifies script execution, doc creation, and index update | e461f6a |
