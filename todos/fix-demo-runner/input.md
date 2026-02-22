# Fix Demo Runner

The demo-runner feature was delivered but its own demo presentation failed. Two root causes.

## Bug 1: Existing demos lack `demo` field in snapshot.json

**Observed:** `telec todo demo themed-primary-color` outputs:

```
Warning: Demo 'themed-primary-color' has no 'demo' field. Skipping execution.
```

**Root cause:** The demo procedure (`software-development/procedure/lifecycle/demo`) specifies a `demo` field -- a shell command string that demonstrates the feature. Both existing demos (`themed-primary-color`, `tui-markdown-editor`) predate this schema addition. Their `snapshot.json` files were migrated (renamed folders, removed `sequence` field) during the demo-runner build, but the `demo` field was never added.

**Location:** `demos/themed-primary-color/snapshot.json` and `demos/tui-markdown-editor/snapshot.json` -- both missing the `demo` field.

**Fix:** Add a `demo` field to each existing snapshot.json with a shell command that shows the feature. Examples:

- `themed-primary-color`: something that shows the theme configuration or color values
- `tui-markdown-editor`: something that shows the editor launch or markdown rendering

## Bug 2: `/next-demo` command passes wrong session_id to render_widget

**Observed:** The `/next-demo` worker called `render_widget` with `"demo"` as the session_id instead of its actual TeleClaude session UUID, resulting in:

```
Error: Session demo not found
```

**Root cause:** The `/next-demo` command artifact (`agents/commands/next-demo.md`) instructs the worker to render a celebration widget via `teleclaude__render_widget` but does not specify how to obtain the session_id. The worker guessed "demo" as the session_id instead of reading it from the environment (`$TMPDIR/teleclaude_session_id`).

**Location:** `agents/commands/next-demo.md` -- Step 3 says "Render celebration widget via `teleclaude__render_widget`" but gives no guidance on the session_id parameter.

**Fix:** The command artifact should instruct the worker to read the session_id from `$TMPDIR/teleclaude_session_id` (the standard mechanism) and pass it to `render_widget`. Example addition:

```
Read session_id from environment: cat $TMPDIR/teleclaude_session_id
Pass it as the session_id parameter to render_widget.
```

## Scope

- Two snapshot.json files need a `demo` field added
- One command artifact needs session_id guidance added
- No Python code changes needed (the CLI runner correctly handles missing `demo` field)
