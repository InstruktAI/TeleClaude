# Fix Demo Runner

The demo-runner feature was delivered but demos don't work. Root cause analysis revealed
two bugs, but the deeper issue is that the demo system's design is wrong.

## Original bugs

1. Existing snapshots lack the `demo` field → `telec todo demo` warns and skips.
2. `/next-demo` command passes wrong session_id to render_widget.

## Actual problem

The demo system hardcodes a single presentation path: run a shell command, render a
celebration widget. This is backwards. A demo is whatever the delivery warrants —
a TUI walkthrough, a CLI output, a Discord observation, a Playwright recording.

The `demo` field (single shell command) is too rigid. The `/next-demo` command
prescribes a fixed ceremony instead of being an adaptive presenter. The demo procedure
doc codifies the widget ceremony.

## Redesign direction (from conversation with Mo)

1. Replace the `demo` shell command field with `demo.md` — a freeform markdown file
   with steps for the presenting AI to execute.
2. Steps can contain executable code blocks (```bash) that `telec todo demo` extracts
   and runs for validation. This gives upfront testability.
3. Steps also contain guided instructions (ask user to observe, narrate what's happening).
4. The AI is always the presenter AND operator. It presses TUI keys, runs Playwright
   for web UI, calls CLI commands. User sits with popcorn.
5. The demo is the ultimate functional test. If it can't be demonstrated, it's not
   delivered. Failed demo → `telec bugs report`, fix forward.
6. `demo.md` is drafted during prepare phase (architect defines how to prove it works),
   refined during build phase (builder has the most context).
7. `snapshot.json` stays as the delivery record (narrative + metrics) but drops the
   `demo` field.

## Scope

- Introduce `demo.md` artifact in todo lifecycle and demo folder
- Rewrite `telec todo demo` CLI to extract and run code blocks from `demo.md`
- Rewrite `/next-demo` command as a conversational presenter that reads `demo.md`
- Update demo procedure doc, demo artifact spec, lifecycle overview
- Write `demo.md` for existing demos (themed-primary-color, tui-markdown-editor)
- Add `demo.md` to todo scaffold
- Update prepare-draft procedure to include demo-steps drafting
