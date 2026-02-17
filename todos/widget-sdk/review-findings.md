# Widget SDK — Review Findings

**Review round:** 1
**Reviewer:** Claude (automated)
**Date:** 2026-02-17
**Scope:** 24 files, 1838 insertions (all additive)
**Merge base:** `main`

---

## Critical

None.

## Important

### 1. Path containment check uses string prefix instead of path boundary

**File:** `teleclaude/api/data_routes.py:37`

```python
if not str(resolved).startswith(str(workspace.resolve())):
```

`str.startswith()` does not respect path boundaries. If `workspace.resolve()` is `/opt/teleclaude/workspace/abc123`, the check passes for `/opt/teleclaude/workspace/abc123evil/secret` (a sibling directory whose name shares the prefix). The `".."` component check on line 32 provides effective defense-in-depth (it catches all `..`-based traversal before this check is reached), so exploitation requires symlink manipulation inside the workspace — a very low-probability vector. Still, this is a correctness bug in the containment logic.

**Fix:** Replace with `Path.is_relative_to()` (available since Python 3.9):

```python
if not resolved.is_relative_to(workspace.resolve()):
    raise HTTPException(status_code=403, detail="Path traversal not allowed")
```

### 2. Synchronous file I/O in async `_store_widget`

**File:** `teleclaude/mcp/handlers.py:1354-1392`

`_store_widget` is declared `async` but performs synchronous `pathlib.Path` operations: `mkdir`, `write_text`, `read_text`, `exists`. These block the event loop for all concurrent sessions during widget library writes.

**Fix:** Wrap in `asyncio.to_thread()`:

```python
await asyncio.to_thread(self._store_widget_sync, session, name, data)
```

### 3. `WidgetIndexEntry` TypedDict has no required fields

**File:** `teleclaude/mcp/types.py:148-157`

`total=False` makes every field optional, including `name` (the primary lookup key used at `handlers.py:1381`). An entry deserialized from corrupted JSON without `name` becomes a dead index row. The handler always constructs entries with `name` and `path` present, but the type permits empty entries.

**Fix:** Use mixed required/optional TypedDict:

```python
class WidgetIndexEntry(TypedDict):
    name: str
    path: str
    title: NotRequired[str]
    description: NotRequired[str]
    updated_at: NotRequired[str]
    renderer: NotRequired[str]
    types: NotRequired[str]
```

## Suggestions

### 4. Missing exhaustiveness guard in section switch

**File:** `frontend/app/components/widgets/RenderWidgetUI.tsx:81`

The `default` branch in `SectionContent` renders `UnknownSection` — correct for forward compatibility with server-sent data. But without a `const _exhaustive: never = section` guard, adding a new section type to the `Section` union compiles silently instead of flagging the missing case. Add the guard before the fallback rendering.

### 5. Style lookup maps discard type narrowing

**File:** `frontend/app/components/widgets/RenderWidgetUI.tsx:21-34`

`STATUS_STYLES` and `VARIANT_STYLES` are typed as `Record<string, string>` instead of `Record<WidgetStatus, string>` / `Partial<Record<SectionVariant, string>>`. Adding a new status value won't produce a compile error for the missing style entry.

### 6. `FileSection.label` overloads `SectionBase.label`

**File:** `frontend/lib/widgets/types.ts:88`

`FileSection` redeclares `label?: string` which TypeScript merges with `SectionBase.label`. The section-level `label` renders as an uppercase heading in `SectionRenderer`, while `FileSectionRenderer` also uses it as the file display name. If an agent sets `label: "Download Report"`, both render — a heading "DOWNLOAD REPORT" above a download link "Download Report". Consider a separate `displayName` field.

### 7. `InputField` is a flat bag instead of discriminated union

**File:** `frontend/lib/widgets/types.ts:26-44`

`InputField.options` is optional on all input types but only meaningful for `"select"`. A select field without `options` silently renders an empty dropdown. Making `InputField` a discriminated union on `input` would make `options` required for `"select"` only. This is a type design improvement, not a runtime bug — the current code handles it defensively.

### 8. Widget text summary not length-capped for Telegram

**File:** `teleclaude/mcp/handlers.py:1291-1310`

The existing `send_result` handler truncates at 4096 chars for Telegram compatibility. The widget handler's `send_message` call does not truncate. Long widget summaries may fail the Telegram send. The try/except catches this, but the plain-text fallback also lacks truncation.

---

## Requirements Coverage

| Requirement                       | Status            | Notes                                                                                                                                                                                                          |
| --------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1: Expression format schema      | Covered           | Types match spec. All section types defined.                                                                                                                                                                   |
| R2: MCP tool definition           | Covered           | Tool + inputSchema with full JSON Schema for sections.                                                                                                                                                         |
| R3: Handler with fanout + library | Covered           | Text summary, adapter fanout, file attachments, library storage.                                                                                                                                               |
| R4: File serving endpoint         | Covered           | Path validation, content-type detection, attachment headers.                                                                                                                                                   |
| R5: Frontend type definitions     | Covered           | Discriminated union, barrel export, all types present.                                                                                                                                                         |
| R6: Section renderers             | Partially covered | All section types rendered. Missing: react-shiki syntax highlighting (CodeSection uses plain `<pre><code>`), Image.Zoom click-to-zoom, FileSection inline previews. Consistent with implementation plan scope. |
| R7: AskUserQuestionUI             | Covered           | Single/multi select, composer send, disable after selection.                                                                                                                                                   |
| R8: ThreadView wiring             | Covered           | `by_name` routing with Fallback preserved.                                                                                                                                                                     |
| R9: AI authoring guide            | Covered           | Complete guide with schema docs and example compositions.                                                                                                                                                      |

## Regression Check

All changes are additive. Existing files modified:

- `ThreadView.tsx` — adds `by_name` routing, `Fallback` preserved
- `api_server.py` — includes new router, no other changes
- `handlers.py` — adds new methods, no changes to existing
- `tool_definitions.py` — adds schema constants and tool, no changes to existing
- `types.py` — adds new TypedDict, no changes to existing
- `mcp_server.py` — adds enum member and handler dispatch, no changes to existing

**No regressions detected.**

## Verdict

**APPROVE**

Findings 1-3 (Important) should be addressed in a follow-up fix-review pass. None are blocking: the path traversal has defense-in-depth from the `..` component check, the sync I/O is a performance concern (not correctness), and the TypedDict looseness is compensated by the handler always populating required fields.
