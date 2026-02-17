# Widget SDK — Implementation Plan

## Approach

Additive feature. One new MCP tool + handler, one new daemon endpoint, a generic section renderer with per-type components, and ThreadView wiring. No changes to SSE pipeline, transcript converter, or Next.js proxy — they already carry tool_use/tool_result events unchanged.

Build backend first (tool def + handler + file endpoint), then frontend (types → section renderers → AskUserQuestion → wiring), then authoring guide.

The expression format is the core design: a flat array of typed sections that agents compose freely. One generic renderer per adapter walks the sections. Web gets React/shadcn. Telegram gets text summary + file attachments (rich Telegram rendering with inline keyboards is deferred to a follow-up). Terminal gets text summary.

## Task Sequence

### Task 1: MCP tool definition + handler (R2, R3) [x]

**Files:**

- `teleclaude/mcp/tool_definitions.py` — add tool definition
- `teleclaude/mcp/handlers.py` — add handler

**Edits:**

- Add `teleclaude__render_widget` to tool list with `session_id` (string) and `data` (object — the expression format blob).
- Tool description documents the expression format: title, hints, sections array, and all section type schemas. This is agent-facing documentation.
- Add handler method: walks `data.sections`, generates text summary per section type, calls `send_result(summary)` for Telegram fanout, calls `send_file()` for each `file`/`image` section with workspace-relative paths, returns summary as tool result.
- **Library collection:** if `data.name` is present, write full expression to `{widgets_dir}/{name}.json` (create or update). Update `widgets/index.json` with `{ name, title, description, renderer?, types?, path, updated_at }`. This is the collection funnel — no separate harvesting needed.

**Verify:** Tool appears in MCP tool list. Handler returns text summary for various section combinations. Adapter fanout calls logged. Named widget stored to `widgets/{name}.json` and index updated.

### Task 2: File serving endpoint (R4) [x]

**Files:**

- `teleclaude/api/data_routes.py` — create new module with router
- `teleclaude/api_server.py` — include router

**Edits:**

- Create `data_routes.py` with `APIRouter(prefix="/data", tags=["data"])`.
- Add `GET /{session_id}` with `file` query param.
- Validate session exists via `db.get_session()`, resolve path within `get_session_output_dir()` (reject `..` traversal).
- Serve with `Content-Type` from `mimetypes.guess_type()`, `Content-Disposition: attachment`.
- In `api_server.py`: `from teleclaude.api.data_routes import router as data_router; self.app.include_router(data_router)`.

**Verify:** Curl returns file content with correct headers. Path traversal attempts return 403. Missing session returns 404.

### Task 3: Frontend type definitions (R1, R5) [x]

**Files:**

- `frontend/lib/widgets/types.ts` — create
- `frontend/lib/widgets/index.ts` — create barrel

**Edits:**

- Define section types as discriminated union on `type` field: `TextSection`, `InputSection`, `ActionsSection`, `ImageSection`, `TableSection`, `FileSection`, `CodeSection`, `DividerSection`.
- Define `InputField`, `Button`, `WidgetExpression`, `Section` union.
- Define `RenderWidgetArgs = { data: WidgetExpression }` and `RenderWidgetResult`.
- Barrel exports all types.

**Verify:** TypeScript compiles clean.

### Task 4: Section renderer components (R6) [x]

**Files:**

- `frontend/app/components/widgets/RenderWidgetUI.tsx`
- `frontend/app/components/widgets/sections/TextSection.tsx`
- `frontend/app/components/widgets/sections/InputSection.tsx`
- `frontend/app/components/widgets/sections/ActionsSection.tsx`
- `frontend/app/components/widgets/sections/ImageSection.tsx`
- `frontend/app/components/widgets/sections/TableSection.tsx`
- `frontend/app/components/widgets/sections/FileSection.tsx`
- `frontend/app/components/widgets/sections/CodeSection.tsx`
- `frontend/app/components/widgets/sections/DividerSection.tsx`
- `frontend/app/components/widgets/WidgetSkeleton.tsx`
- `frontend/app/components/widgets/index.ts`

**Edits:**

- `RenderWidgetUI`: `makeAssistantToolUI` with `toolName: "teleclaude__render_widget"`. Render callback: show `WidgetSkeleton` while running, then render Card with optional title + section walker.
- Section walker: `for (section of args.data.sections)` → switch on `section.type` → render corresponding component. Unknown types render as collapsed JSON.
- `TextSection`: render markdown content (reuse `MarkdownContent` or dangerouslySetInnerHTML with markdown parser).
- `InputSection`: render form fields from `fields` array (text inputs, selects, checkboxes). Submit sends values via `useComposerRuntime()`.
- `ActionsSection`: render buttons (horizontal or vertical per layout hint). Click sends `"Action: {button.action}"` via composer.
- `ImageSection`: `<img>` with `src="/data/{sessionId}?file={section.src}"`.
- `TableSection`: HTML table from headers + rows.
- `FileSection`: file icon + name + download link to `/data/{sessionId}?file={section.path}`.
- `CodeSection`: `<pre><code>` with language class for syntax highlighting.
- `DividerSection`: `<Separator />` from shadcn/ui.
- `WidgetSkeleton`: shimmer/pulse animation placeholder.

**Verify:** TypeScript compiles. Components render test expressions with various section combinations.

### Task 5: AskUserQuestionUI (R7) [x]

**Files:**

- `frontend/app/components/widgets/AskUserQuestionUI.tsx`

**Edits:**

- `makeAssistantToolUI` for `toolName: "AskUserQuestion"`, or a plain component registered via `by_name`.
- Render question text as card header.
- Render options as clickable cards: radio-style for single select, checkbox-style for multi-select.
- Click sends the selected option number (e.g., "1") as text via `useComposerRuntime()`. The SSE transport sends it to tmux with enter.
- Track selected state locally; disable options after selection.
- When `status.type === "complete"`, show read-only selected state.

**Verify:** TypeScript compiles. Renders with mock AskUserQuestion args. Click triggers composer send.

### Task 6: ThreadView wiring (R8) [x]

**Files:**

- `frontend/components/assistant/ThreadView.tsx`

**Edits:**

- Import `RenderWidgetUI` and `AskUserQuestionUI`.
- Replace `tools: { Fallback: ToolCallBlock }` with:
  ```
  tools: {
    by_name: {
      teleclaude__render_widget: RenderWidgetUI,
      AskUserQuestion: AskUserQuestionUI,
    },
    Fallback: ToolCallBlock,
  }
  ```

**Verify:** TypeScript compiles. Existing ToolCallBlock still renders for unregistered tools.

### Task 7: AI authoring guide (R9) [x]

**Files:**

- `frontend/lib/widgets/AUTHORING.md`

**Edits:**

- Complete guide: expression format schema, all section types with field definitions, layout hints, adapter rendering behavior.
- Example compositions: simple notification (text + actions), onboarding form (text + input + actions), file gallery (text + image + file rows), data report (text + table + file export).
- Documents: "agents describe intent, adapters translate. Web renders richly. Telegram gets text + files. Terminal gets text."

**Verify:** AI agent can follow the guide to compose a new widget expression.

## Scope Decision

20 files across Python + TypeScript. This is larger than typical but justified:

- Backend (4 files): tool def, handler, data endpoint, router inclusion — tightly coupled, must be done together.
- Frontend types (2 files): types + barrel — prerequisites for all components.
- Section renderers (11 files): 8 section components + RenderWidgetUI + skeleton + barrel. Each section component is small (20-50 lines) and follows the same pattern. A builder can scaffold these quickly.
- AskUserQuestion (1 file): standalone, can be deferred if context runs low.
- Wiring (1 file): small change to ThreadView.
- Guide (1 file): markdown, can be deferred if context runs low.

**Recommendation:** Keep as single todo. Tasks have clear verification points. If context exhaustion occurs, remaining tasks (7 → 6 → 5) are deferable and become a follow-up todo.

## Risks and Assumptions

| Risk                                                                    | Impact                             | Mitigation                                                                                              |
| ----------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `makeAssistantToolUI` API may differ between docs and installed version | Blocks frontend tasks 4–6          | API researched and indexed. Verify import works at build time.                                          |
| `by_name` tool routing structure may vary                               | Blocks task 6                      | Confirmed: `tools: { by_name: { name: Component }, Fallback: Component }` in `MessagePrimitive.Content` |
| Composer may be disabled during running tool calls                      | Blocks AskUserQuestion interaction | SSE transport handles message sending independently of tool state. Test with live stream.               |
| Section components may need session ID for file URLs                    | Adds prop drilling                 | Pass session ID via React context or extract from runtime URL.                                          |
| Cross-cutting (Python + TypeScript) may exceed single session           | Context exhaustion                 | Defer tasks 7 → 6 → 5 as follow-up if needed.                                                           |

## Resolved Questions (from research)

1. **`args` is a pre-parsed typed object (TArgs)**, not a string. `argsText` is the raw JSON string. Section walker on `args.data.sections` works directly.
2. **`by_name` routing** works via `MessagePrimitive.Content`: `tools: { by_name: { toolName: Component }, Fallback: Component }`.
3. **Sending messages from tool UIs** uses `useComposerRuntime()` hook: `composer.setText("message"); composer.send();`
4. **Keys endpoint exists**: `POST /sessions/{session_id}/keys` sends keystrokes to tmux. But `useComposerRuntime` + SSE transport achieves the same effect (message → `send_keys_existing_tmux` with `send_enter=True`).
5. **Session workspace**: `get_session_output_dir(session_id)` returns `workspace/{session_id}/`. Files are cleaned up with session.

## Deferred to follow-up

- Rich Telegram rendering: inline keyboards for actions, sequential prompts for input, Mini Apps.
- WhatsApp Business API adapter rendering.
- Custom named renderers: loading `renderer` from index to override generic section walker for specific named widgets.
- Widget hints beyond layout: animations, themes, responsive breakpoints.
- Curation UI: marking widgets as `promoted` in the index for quality filtering.
