---
description: Sync todos with architecture docs and codebase. Detects AND fixes drift autonomously.
---

# Sync Todos

Autonomous sync of todos against architecture and codebase. Detects AND fixes drift.

## Process

### Phase 1: Parallel Scanning (launch all 3 simultaneously)

**Agent 1: Architecture Scanner** (`subagent_type=Explore`)

```text
Discover and read architecture docs in docs/ folder.
Look for: architecture.md, use-cases.md, design docs, domain logic docs.

Return JSON:
{
  "actors": ["list of required actors/components"],
  "features": ["list of features that must exist"],
  "todos_implied": ["slugs that should exist based on architecture"]
}
```

**Agent 2: Codebase Scanner** (`subagent_type=Explore`)

```text
Scan source directories for implemented features.
Identify main modules and what they implement.

Return JSON:
{
  "implemented": ["feature-slug-1", "feature-slug-2"],
  "modules": {"feature-slug": "path/to/module"}
}
```

**Agent 3: Todos Scanner** (`subagent_type=Explore`)

```text
Read todos/roadmap.md

Return JSON:
{
  "pending": ["slug1", "slug2"],
  "completed": ["slug3", "slug4"],
  "folders": ["todos/slug1/", "todos/slug2/"]
}
```

### Phase 2: Reconciliation & Fix

After agents return, identify issues AND fix them:

| Issue                                   | Action (do in this order)                                                                                                                                                    |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Todo marked complete but code missing   | Mark as pending in roadmap.md                                                                                                                                                |
| Code exists but todo marked pending     | Mark as complete in roadmap.md                                                                                                                                               |
| Folder exists but not in roadmap        | Add to roadmap or delete folder                                                                                                                                              |
| Completed todo folder ready to finalize | 1) Append log line to todos/delivered.md, 2) remove the item from roadmap.md entirely (delivered items do not stay on the roadmap), 3) delete `todos/{slug}/` after logging. |
| Todo obsolete (not in architecture)     | Remove from roadmap (no delivered log)                                                                                                                                       |

**Directly edit (be explicit):**

- `todos/roadmap.md` - adjust status and remove delivered items entirely; do **not** record deliveries here.
- `todos/delivered.md` - for every completed todo being delivered, append exactly one line (pipe-delimited): `YYYY-MM-DD | {slug} | {title/description} | outcome | PR/commit`. Create the file if missing. Example: `2025-12-13 | add-login | add login flow | DELIVERED | PR #123`.
- Delete delivered folders after logging and roadmap removal: remove `todos/{slug}/` once delivery is recorded.
- Delete only obsolete folders (not delivered) after confirming they are not needed.

### Phase 3: Report Changes Made

Output a summary of CHANGES MADE (not recommendations):

```text
## Sync Complete

**Fixed:**
- Marked X items complete (code found)
- Marked X items pending (code missing)
- Added X missing items to roadmap
- Removed X obsolete items

**Deleted folders:**
- todos/stale-item-1/
- todos/stale-item-2/

**Manual review needed:**
- [only genuinely ambiguous items]
```

### Phase 4: Commit (optional)

If changes were made, offer to commit:

```bash
git add todos/
git commit -m "chore(todos): sync roadmap with architecture and codebase"
```

---

## Execution

Launch agents now, reconcile results, make fixes, report changes.

**Begin sync...**
