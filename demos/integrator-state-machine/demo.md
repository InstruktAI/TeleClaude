# Demo: integrator-state-machine

## Validation

```bash
# Verify CLI command exists and shows usage
telec todo integrate --help
```

```bash
# Verify API route responds (no active candidates expected in demo)
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X POST "http://localhost/todos/integrate" \
  -H 'Content-Type: application/json' \
  -d '{"cwd": "'$(pwd)'"}' | python3 -m json.tool
```

```bash
# Verify lifecycle events are registered in the event schema
telec events list | grep 'integration\.'
```

```bash
# Verify the state machine module loads without import errors
python3 -c "from teleclaude.core.integration.state_machine import next_integrate; print('OK')"
```

## Guided Presentation

### Step 1: The entry point

Show the CLI command that mirrors `telec todo work`:

```
telec todo integrate
```

**Observe:** Without a READY candidate in the queue, the state machine returns an idle
instruction — no lease acquired, nothing to process. This is the quiescent state.

**Why it matters:** The command is safe to call at any time. No READY candidates = no action.

### Step 2: The state machine loop

When a candidate is READY (review approved, branch pushed, finalized), calling
`telec todo integrate` starts the lifecycle:

1. **First call:** acquires lease, pops candidate, checks clearance, performs squash merge.
   Returns: staged changes, branch commits, requirements, plan — asks agent to compose
   commit message.
2. **Agent acts:** composes and runs `git commit`.
3. **Second call:** detects commit, runs delivery bookkeeping (roadmap deliver, demo
   snapshot), pushes to main. Returns: success or push-rejected instruction.
4. **Third call:** cleanup (worktree, branch, todo dir), daemon restart, marks integrated.
5. **Fourth call:** pops next candidate or returns exit instruction.

**Observe:** Each call advances exactly one phase. The agent only acts at decision points.
The state machine handles all deterministic sequencing.

**Why it matters:** The agent cannot skip steps or miorder operations. The state machine
is the authority on sequencing; the agent is the authority on intelligence.

### Step 3: Crash recovery (idempotency)

If the agent crashes mid-integration, the checkpoint persists on disk. The next
`telec todo integrate` call reads the checkpoint and resumes from the last completed
phase — no duplicate merges, no lost state, no re-acquired leases.

**Observe:** Idempotent re-entry at every phase boundary. The checkpoint is the
single source of truth for integration progress.

### Step 4: Conflict handling

When a squash merge hits conflicts, the state machine returns the conflicted file list
and pauses at the MERGE_CONFLICTED decision point. The agent resolves conflicts, stages,
commits. The next call detects the resolution and continues to delivery.

**Observe:** The state machine provides conflict context but never attempts resolution —
that requires agent intelligence. Clean separation of concerns.

### Step 5: Lifecycle events

Every state transition emits an event through the pipeline. Filter by `integration.*`
to see the full timeline of one integration run:

```
telec events list | grep integration
```

**Observe:** The events provide full observability — from lease acquisition through
candidate delivery. Each event carries the integrator session ID for reconstruction.
