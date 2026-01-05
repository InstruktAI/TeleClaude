# Next Machine - Requirements

## Problem

The current `next-work` command is 13KB of prose that AIs must interpret. This leads to non-deterministic behavior and confusion about what to do next.

## Solution

Create two MCP tools that split the workflow into distinct phases:

- **`teleclaude__next_prepare`** - Phase A: Collaborative architect work (requirements, implementation plan)
- **`teleclaude__next_work`** - Phase B: Deterministic builder work (build, review, fix, finalize)

Both tools:

- Derive state from files (stateless)
- Return exactly ONE action per call
- Enable any agent to orchestrate work

**Separation benefit:** Run `next-prepare` to batch-prepare multiple items, then run `next-work` to churn through them.

---

## Common Signature Pattern

```python
teleclaude__next_prepare(
    slug: str | None = None,  # Optional - if not provided, resolves from roadmap
    cwd: str | None = None    # AUTO-INJECTED by MCP wrapper
) -> NextPrepareResult

teleclaude__next_work(
    slug: str | None = None,  # Optional - if not provided, todos/bugs.md will be checked for items
    cwd: str | None = None    # AUTO-INJECTED by MCP wrapper
) -> NextWorkResult
```

**Project path is NOT a parameter.** The wrapper injects `cwd` automatically via `os.getcwd()`. This works identically whether via TeleClaude or local terminal.

---

# Part 1: Next Prepare (Phase A)

## Purpose

Transform a roadmap item into a ready-to-build work item by discovering requirements and creating an implementation plan through collaborative AI architect sessions.

## Orchestrator Behavior (Collaborative)

Unlike builders (fire-and-forget), architects work collaboratively:

1. Orchestrator calls `teleclaude__next_prepare(slug?)`
2. If dispatch returned → Orchestrator starts architect session AND ENGAGES as sparring partner
3. Back-and-forth discussion until deliverable is complete
4. Orchestrator calls `teleclaude__next_prepare` again to check state
5. Repeat until `action: "prepared"`

## State Detection Flow

```
1. RESOLVE SLUG
   └─ From argument OR from roadmap ([>] priority, then [ ])
   └─ If nothing found → return error NO_WORK

2. CHECK REQUIREMENTS
   └─ todos/{slug}/requirements.md exists?
      NO → return dispatch "/next-prepare"

3. CHECK IMPLEMENTATION PLAN
   └─ todos/{slug}/implementation-plan.md exists?
      NO → return dispatch "/next-prepare"

4. PREPARED
   └─ return prepared
```

## Return Format

The tool returns **plain text** that the orchestrator AI executes literally.

### Tool Call (dispatch architect)

```
TOOL_CALL:
teleclaude__run_agent_command(
  computer="local",
  command="next-prepare", # does not yet exist as command, but will be created and should contain instructions to engage collaboratively to deliver the (remaining) required files
  args="my-slug", # or a reference to the roadmap item that is used as input to kick off the other agent
  project="/path/to/project",
  agent="claude",
  thinking_mode="slow",
)

NOTE: Engage as collaborator - this is an architect session requiring discussion.
```

### Prepared (ready for work phase)

```
PREPARED:
todos/my-slug is ready for work.
Run teleclaude__next_work() to start the build/review cycle.
```

### Error state

```
ERROR: NO_WORK
No pending items in roadmap.
```

## Agent Fallback (Prepare)

| Task         | Preferred     | Fallback 1    |
| ------------ | ------------- | ------------- |
| requirements | claude (slow) | gemini (slow) |
| plan         | claude (slow) | gemini (slow) |

## Architect Commands

### /next-requirements

**Purpose:** Discover and document requirements for a roadmap item

**Agent:** Claude (slow) - needs deep thinking

**Collaboration pattern:**

1. Architect reads roadmap item description
2. Architect explores codebase to understand current architecture
3. Architect proposes requirements to orchestrator (sparring partner)
4. Back-and-forth refinement
5. Architect writes `todos/{slug}/requirements.md`
6. Architect commits the file

**Output:** `todos/{slug}/requirements.md`

---

### /next-plan

**Purpose:** Create implementation plan from requirements

**Agent:** Claude (slow) - needs architectural thinking

**Collaboration pattern:**

1. Architect reads `todos/{slug}/requirements.md`
2. Architect explores codebase for patterns, dependencies, integration points
3. Architect proposes implementation approach to orchestrator
4. Back-and-forth refinement on grouping, ordering, risk areas
5. Architect writes `todos/{slug}/implementation-plan.md` with Groups 1-4+ structure
6. Architect commits the file

**Output:** `todos/{slug}/implementation-plan.md`

---

## State Transitions (next_prepare)

```
                    ┌─────────────────┐
                    │   START         │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Has requirements?│──NO──► dispatch /next-requirements
                    └────────┬────────┘                │
                             │                         │
                             │            (orchestrator collaborates)
                             │                         │
                             │◄────────────────────────┘
                    ┌────────▼────────┐
                    │ Has impl-plan?  │──NO───► dispatch /next-plan
                    └────────┬────────┘                │
                             │                         │
                             │            (orchestrator collaborates)
                             │                         │
                             │◄────────────────────────┘
                    ┌────────▼────────┐
                    │    PREPARED     │
                    └─────────────────┘
```

---

# Part 2: Next Work (Phase B)

## Purpose

Execute deterministic build/review/fix cycle on prepared work items. Only operates on items that already have requirements and implementation plan.

## Orchestrator Behavior (Fire-and-Forget)

Unlike architects, builders work independently:

1. Orchestrator calls `teleclaude__next_work(slug?)`
2. If dispatch returned → Orchestrator starts worker session and waits for completion notification
3. No engagement - worker operates autonomously
4. Orchestrator calls `teleclaude__next_work` again
5. Repeat until `action: "complete"`

---

## Agent Availability & Fallback

### Problem

Agents (Codex, Claude, Gemini) can become unavailable due to:

- Rate limits
- Quota exhaustion ("you have spent all your credits, come back at 5pm")
- Service outages

### Availability State

Store in database (new table `agent_availability`):

```sql
CREATE TABLE agent_availability (
    agent TEXT PRIMARY KEY,     -- "codex", "claude", "gemini"
    available BOOLEAN,
    unavailable_until TEXT,     -- ISO timestamp, NULL if available
    reason TEXT                 -- "quota_exhausted", "rate_limited", "service_outage"
);
```

### Fallback Matrix

When preferred agent unavailable, fall back to next in list:

| Task     | Preferred     | Fallback 1    | Fallback 2    |
| -------- | ------------- | ------------- | ------------- |
| build    | gemini (med)  | claude (med)  | codex (med)   |
| review   | codex (slow)  | claude (slow) | gemini (slow) |
| fix      | claude (med)  | gemini (med)  | codex (med)   |
| finalize | claude (med)  | gemini (med)  | codex (med)   |
| commit   | claude (fast) | gemini (fast) | codex (fast)  |

### Detection & Marking

When a dispatch fails with availability error:

1. Orchestrator reports failure to `teleclaude__mark_agent_unavailable(agent, unavailable_until, reason)` tool
2. Returns next dispatch with fallback agent

NOTE: unavailability MUST also be flagged when the agent becomes unresponsive or a message is seen indicating business. Especially Gemini has a habit of saying they're overloaded.
In such cases we will need to set a reasonable `unavailable_until` time (e.g., 1 hour later).

### Auto-Recovery

When `teleclaude__next_work` is called:

1. Check `agent_availability` table
2. For any agent where `unavailable_until < NOW()`:
   - Mark as `available = true`
   - Clear `unavailable_until` and `reason`

### Tool Interaction

Orchestrator marks unavailability:

```python
teleclaude__mark_agent_unavailable(
    agent: str,              # "codex", "claude", "gemini"
    unavailable_until: str,  # ISO timestamp
    reason: str              # "quota_exhausted", etc.
)
```

### Selection Logic in `next_work`

```
1. Determine task type (bugs, build, review, fix, commit)
2. Get fallback list for task type
3. For each agent in fallback list:
   - Check agent_availability
   - If available OR unavailable_until < NOW():
     - Return dispatch for this agent
4. If preferred agents unavailable:
   - Fall back to orchestrator agent itself as final resort
```

---

## Slug Resolution

When `slug` is not provided:

1. Parse `todos/roadmap.md`
2. Find first item marked `[>]` (in-progress) - priority
3. If none, find first item marked `[ ]` (pending)
4. Extract slug from item
5. If `[ ]` found, mark it `[>]` in roadmap

---

## Return Format

The tool returns **plain text** that the orchestrator AI executes literally. No JSON interpretation needed.

### Tool Call (dispatch worker)

```
TOOL_CALL:
teleclaude__run_agent_command(
  computer="local",
  command="next-build",
  args="my-slug",
  project="/path/to/project",
  agent="gemini",
  thinking_mode="med",
  subfolder="trees/my-slug"
)
```

### Prepared (ready for work phase)

```
PREPARED:
todos/my-slug is ready for work.
Run teleclaude__next_work() to start the build/review cycle.
```

### Complete (work finalized)

```
COMPLETE:
todos/my-slug has been finalized.
Delivered to done/005-my-slug/
```

### Error states

```
ERROR: NO_WORK
No pending items in roadmap.
```

```
ERROR: NOT_PREPARED
todos/my-slug is missing implementation plan.
Run teleclaude__next_prepare("my-slug") first.
```

---

## State Detection Flow

The tool executes these checks in order:

```
1. RESOLVE SLUG
   └─ From argument OR from roadmap ([>] priority, then [ ])
   └─ If nothing found → return error NO_WORK

2. CHECK IF FINALIZED
   └─ done/*-{slug}/ directory exists?
      YES → return complete

3. VALIDATE PRECONDITIONS
   └─ todos/{slug}/requirements.md AND todos/{slug}/implementation-plan.md exist?
      NO → return error NOT_PREPARED

4. ENSURE WORKTREE (automated)
   └─ trees/{slug} directory exists?
      NO → execute: git worktree add trees/{slug} -b {slug}

5. CHECK UNCOMMITTED CHANGES
   └─ git status in trees/{slug} shows uncommitted changes?
      YES → return dispatch "/commit-pending"

6. CHECK BUILD STATUS
   └─ Parse impl-plan, any [ ] in Groups 1-4?
      YES → return dispatch "/next-build"

7. CHECK REVIEW STATUS
   └─ todos/{slug}/review-findings.md exists?
      NO → return dispatch "/next-review"

8. CHECK REVIEW VERDICT
   └─ review-findings.md contains "[x] APPROVE"?
      NO → return dispatch "/next-fix-review"

9. DISPATCH FINALIZE
   └─ return dispatch "/next-finalize"
   (complete is returned on next call when step 2 passes)
```

NOTE: codex needs commands to start with `/prompts:` prefix, so the automation should prepend that if it is chosen as agent.

---

## Automated Operations

### Worktree Creation (Step 4)

Tool executes internally before returning:

```bash
git worktree add trees/{slug} -b {slug}
```

NOTE: Finalize is NOT automated - it's dispatched to /next-finalize worker.
Merge conflicts, push failures, and network issues need AI judgment to resolve.

---

## Worker Commands

### /next-build

**Purpose:** Implement all tasks in Groups 1-4 of the implementation plan

**Agent:** Claude (med)

**What it does:**

1. Reads `todos/{slug}/requirements.md`
2. Reads `todos/{slug}/implementation-plan.md`
3. For each unchecked task in Groups 1-4:
   - Makes code changes
   - Runs tests
   - Updates checkbox `[ ]` → `[x]`
   - Commits changes
4. Reports completion

**Commits:** Yes - worker commits after each task

---

### /next-review

**Purpose:** Review code against requirements

**Agent:** Codex (slow)

**What it does:**

1. Reads `todos/{slug}/requirements.md`
2. Reads `todos/{slug}/implementation-plan.md`
3. Runs `git diff $(git merge-base HEAD main)..HEAD`
4. Evaluates: requirements coverage, code quality, tests, security
5. Writes `todos/{slug}/review-findings.md` with verdict:
   - `[x] APPROVE` - ready to merge
   - `[x] REQUEST CHANGES` - needs fixes
6. Commits the review file

**Commits:** Yes - worker commits review-findings.md

---

### /next-fix-review

**Purpose:** Fix issues identified in code review

**Agent:** Claude (med)

**What it does:**

1. Reads `todos/{slug}/review-findings.md`
2. Reads `todos/{slug}/requirements.md`
3. For each issue in Critical/Important sections:
   - Makes the fix
   - Runs tests
4. **Deletes** `todos/{slug}/review-findings.md`
5. Commits all changes

**Commits:** Yes - worker commits fixes AND the review file deletion

**Why delete review file:** Forces state machine back to "needs review" for fresh evaluation of fixes.

---

### /commit-pending

**Purpose:** Safety net - commit any uncommitted changes

**Agent:** Claude (med)

**What it does:**

1. Checks git status
2. Crafts appropriate commit message based on changes
3. Commits

**When dispatched:** When tool detects uncommitted changes in worktree (previous worker forgot to commit)

---

## State Transitions (next_work)

```
                    ┌─────────────────┐
                    │   START         │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Finalized?      │──YES──► COMPLETE
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Prepared?       │──NO──► error NOT_PREPARED
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Worktree exists?│──NO──► [AUTO: create worktree]
                    └────────┬────────┘                │
                             │◄────────────────────────┘
                    ┌────────▼────────┐
                    │ Uncommitted?    │──YES──► dispatch /commit-pending
                    └────────┬────────┘                │
                             │◄────────────────────────┘
                    ┌────────▼────────┐
                    │ Groups 1-4 done?│──NO───► dispatch /next-build
                    └────────┬────────┘                │
                             │◄────────────────────────┘
                    ┌────────▼────────┐
                    │ Review exists?  │──NO───► dispatch /next-review
                    └────────┬────────┘                │
                             │◄────────────────────────┘
                    ┌────────▼────────┐
                    │ APPROVE?        │──NO───► dispatch /next-fix-review
                    └────────┬────────┘                │
                             │                         │
                             │            (fix worker deletes review file)
                             │                         │
                             │◄────────────────────────┘
                    ┌────────▼────────┐
                    │dispatch finalize│───────► (worker merges, archives)
                    └────────┬────────┘                │
                             │                         │
                             │◄────────────────────────┘
                             │    (next call: Finalized? → YES)
                    ┌────────▼────────┐
                    │    COMPLETE     │
                    └─────────────────┘
```

---

## Implementation Checklist

### New MCP Tools

- [ ] `teleclaude__next_prepare` in `teleclaude/mcp_server.py`
- [ ] `teleclaude__next_work` in `teleclaude/mcp_server.py`
- [ ] `teleclaude__mark_agent_unavailable` in `teleclaude/mcp_server.py`

### Database

- [ ] `agent_availability` table with availability tracking

### New Builder Commands

- [ ] `/commit-pending` command in `~/.agents/commands/`
- [ ] `/next-fix-review` command in `~/.agents/commands/`

### Updated Commands

- [ ] `/next-build` - ensure it commits after each task
- [ ] `/next-review` - ensure verdict format matches `[x] APPROVE`

### Orchestrator Commands

- [ ] `/next-prepare` - calls tool and engages collaboratively with architect
- [ ] `/next-work` - calls tool and dispatches workers
