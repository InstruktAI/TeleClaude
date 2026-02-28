# Demo: todo-dump-command

## Validation

```bash
# Verify the dump subcommand exists in help
telec todo --help 2>&1 | grep -q "dump" && echo "PASS: dump subcommand in help" || echo "FAIL"
```

```bash
# Dump a test todo and verify scaffold + input content
TEST_SLUG="demo-dump-test-$(date +%s)"
telec todo dump "This is a brain dump test for demo validation" --slug "$TEST_SLUG"
test -f "todos/$TEST_SLUG/input.md" && echo "PASS: input.md created" || echo "FAIL"
grep -q "brain dump test" "todos/$TEST_SLUG/input.md" && echo "PASS: content written" || echo "FAIL"
grep -q "$TEST_SLUG" todos/roadmap.yaml && echo "PASS: registered in roadmap" || echo "FAIL"
# Cleanup
telec todo remove "$TEST_SLUG" 2>/dev/null
```

```bash
# Verify auto-slug generation
telec todo dump "My Amazing Feature Idea" 2>&1 | grep -q "my-amazing-feature-idea" && echo "PASS: auto-slug" || echo "FAIL"
# Cleanup
telec todo remove "my-amazing-feature-idea" 2>/dev/null
```

## Guided Presentation

### Step 1: Show the command exists

Run `telec todo --help` and observe the new `dump` subcommand in the list, alongside
`create`, `remove`, `validate`, etc. The description reads "Fire-and-forget brain dump
with notification trigger."

### Step 2: Dump a brain dump

Run:

```
telec todo dump "Add a caching layer for API responses to reduce latency"
```

Observe:

- Auto-generated slug `add-a-caching-layer-for-api-responses` (truncated to 40 chars)
- Scaffold created at `todos/add-a-caching-layer-for-api-respon/`
- `input.md` contains the full brain dump text
- Confirmation that the `todo.dumped` notification was sent

### Step 3: Verify the artifacts

Inspect `todos/<slug>/input.md` — the brain dump text is there, ready for an agent to
flesh out into requirements and an implementation plan.

Inspect `todos/roadmap.yaml` — the slug is registered and visible in the preparation queue.

### Step 4: Show the notification flow

Check `telec events list` (if notification service is active) to see the `todo.dumped`
event was emitted. The prepare-quality-runner agent would pick this up and autonomously
process the todo through DOR assessment.

### Step 5: Compare with `create`

Run `telec todo create manual-test` — observe it creates a skeleton with template
`input.md` (empty). No notification is fired. This is the deliberate, human-driven path.
The dump command is the fire-and-forget, agent-driven path.
