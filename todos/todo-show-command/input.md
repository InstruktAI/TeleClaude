# todo-show-command — Input

Implement telec todo show <slug> — a single-call command that returns the complete actionable view of a todo for any agent.

## Response Payload Design

The payload is assembled from todo_state + todo_artifacts + roadmap tables. It is NOT a raw schema dump — it is a curated, actionable view that shows only what matters for the current lifecycle position.

### Top-level keys (conditional — omit when empty/null):
- slug: the todo identifier
- description: from roadmap table
- stage: prepare | work | integrate | delivered
- blocked_by: only when undelivered dependencies exist (see graph structure below)
- previous: the completed phase before current (string or object with phase details)
- current: always present, object with phase + state
- next: only when current.state == done
- artifacts: object keyed by artifact name, values are full content strings

### current object:
- phase: the lifecycle phase name (input_assessment, discovery, requirements_review, build, review, fix, finalize, etc.)
- state: in_progress | done
- When done: include phase-specific completion data (status, verdict, round, etc.)
- When in_progress: no extra data beyond phase and state

### next key:
- ONLY appears when current.state == done
- Just the phase name string — no data exists yet for the next phase

### previous key:
- The phase that completed before current
- Simple string when no special context needed (e.g. 'build')
- Object with phase + verdict/details when context matters (e.g. review that requested changes)
- Omitted entirely for fresh todos with no history

### blocked_by (dependency graph):
- Only present when undelivered dependencies exist
- Array of objects, each with: slug, stage, current (phase name)
- Nested: each blocker shows its own blocked_by if it has undelivered deps
- This gives the agent the full transitive graph to understand the path to unblock
- Example: [{slug: 'mesh-architecture', stage: 'prepare', current: 'input_assessment'}, {slug: 'community-governance', stage: 'prepare', current: 'input_assessment', blocked_by: ['mesh-architecture']}]

### artifacts:
- All stored artifacts for the slug, keyed by name
- Content is the full text, not truncated
- Only artifacts that exist — no empty keys

### Conditional field rules:
- No null values anywhere in the payload
- No empty arrays or objects
- Keys only appear when they carry meaning
- description only if set in roadmap
- blocked_by only if undelivered deps exist
- previous only if a phase has completed
- next only if current.state == done

## CLI Surface

telec todo show <slug> — registered under todo subcommands
Goes through daemon API: GET /todos/{slug}/show
The API handler assembles the payload by reading todo_state, todo_artifacts, and roadmap tables, then applies the conditional filtering logic.

## Also in scope:

1. Merge telec todo read and telec todo artifacts into telec todo artifacts {list|read|write}
   - telec todo artifacts list <slug> — list artifact names
   - telec todo artifacts read <slug> <name> — read content
   - telec todo artifacts write <slug> <name> --file <path> — write content
   - All positional args except --file

2. Remove telec todo read and telec todo write as separate commands
   - They are now subcommands under artifacts

3. Update CLI surface definition for all changes

4. Add telec todo artifacts read to global @exec expansion in telec-cli spec (the only globally expanded artifact command)

5. Add Required tools section to snippet-authoring-schema as optional procedure section
   - Tools listed in procedures are the tools for that job — available on the wall, grabbed when needed
   - Not all must be used, but they are the right tools for the work
   - No per-procedure boilerplate — the concept of Required tools is defined once

6. Telec roadmap list cleanup — remove frivolous fields:
   - Keep: slug, description, status, after (only if deps exist), group (only if set)
   - Remove: has_requirements, has_impl_plan, build_status, review_status, dor_score, deferrals_status, findings_count, files, todo_path, prepare_phase, integration_phase, finalize_status, current
   - No null/empty fields

7. Full datetime for delivery timestamps (already done in todos.db deliver method)
