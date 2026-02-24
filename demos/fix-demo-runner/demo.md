# Demo: fix-demo-runner

## Validation

Verify the demo validator runs and exits 0 for existing demos.

```bash
telec todo demo themed-primary-color
```

```bash
telec todo demo tui-markdown-editor
```

Verify the scaffold creates demo.md.

```bash
telec todo create test-demo-scaffold && test -f todos/test-demo-scaffold/demo.md && echo "demo.md exists" && rm -rf todos/test-demo-scaffold
```

## Guided Presentation

### What to show

The demo system has been redesigned around `demo.md` — a freeform markdown file
that replaces the rigid `demo` shell command field in `snapshot.json`.

- **Demo validator:** `telec todo demo <slug>` extracts fenced bash code blocks
  from `demo.md` and runs them sequentially. All must exit 0. This is a build gate.
- **Conversational presenter:** `/next-demo <slug>` reads `demo.md` and walks
  through all steps — executing code blocks, operating the system for guided steps,
  and checking verification assertions.
- **Scaffold integration:** `telec todo create <slug>` now includes a `demo.md`
  template alongside the other preparation artifacts.

### What to narrate

The key insight is that demos are written by one AI for another AI to execute.
The architect drafts `demo.md` during prepare (how to prove it works), the builder
refines it with real implementation knowledge during build. The demo validator
ensures it passes as a build gate before handoff to review. After delivery,
`/next-demo` reads the same file and presents it conversationally to the user.
