# Code Context Auditor

## The Big Picture

This is Phase 2 of the self-documenting codebase vision. Phase 1 (code-context-annotations) gives us the annotations — agents write `@context` tags in docstrings, a scraper turns them into discoverable snippets. Phase 2 closes the feedback loop: an auditor compares what annotations _claim_ against what the code _actually does_, producing actionable findings.

The combined system creates a self-correcting feedback loop:

```
Agents write code
    → Agents annotate code (Phase 1: proximity makes this easy)
    → Auditor checks annotations against code (Phase 2: this todo)
    → Findings surface drift, scope creep, naming inconsistencies
    → Agents fix the code OR fix the annotation
    → Better code + better docs
    → Loop
```

## Why This Matters

### The Data Lake

Once you have a critical mass of annotations — say, 50+ modules/classes annotated — the corpus becomes a queryable model of the codebase's self-understanding. Each annotation says "I am responsible for X." The auditor can then ask:

- **Does this code actually do X?** Maybe it does X+Y+Z now. That's scope creep.
- **Does anything else also claim to do X?** Overlapping responsibility = coupling.
- **Does the naming match the declared purpose?** A module called `message_ops` annotated as "manages footer delivery" has a naming problem.
- **Are there modules that should be annotated but aren't?** Large, complex files with no annotation are blind spots.
- **Do cross-references make sense?** If module A says "does NOT handle Y" and module B doesn't claim Y either, who handles Y?

These aren't documentation questions. They're architectural health questions. The annotations are just the data source.

### External Consumers

When a remote agent (no codebase access) asks "what does this project do?", it queries `get_context` and gets back the annotation corpus. If the annotations are accurate and granular, the answer is accurate and granular. If the auditor has been running, the annotations have been continuously verified. The external consumer gets a trustworthy view of the system.

This is the path to agents that can answer questions about any codebase they've never seen — not from a stale README, but from living, verified, machine-readable documentation.

### Self-Improvement

This is the most subtle and powerful part. The auditor doesn't just find problems — it generates signals that feed back into the agent's own improvement:

- **Architectural clarity** — When the auditor flags scope creep, the fix often reveals a module that needs splitting. The agent learns from this pattern.
- **Naming precision** — When the auditor flags naming drift, the rename makes the code more navigable for every future agent.
- **Boundary enforcement** — When the auditor confirms that annotations match reality, it reinforces the discipline of writing boundary statements.

Agents that use this system will get better at structuring code because the audit findings teach them what "good structure" looks like. The system improves itself not through rules, but through continuous feedback.

## The Prompting Challenge

The auditor is an AI reading annotations and code, then making judgments about consistency. The quality of its output depends entirely on how it's prompted. Key challenges:

### 1. What counts as "inconsistent"?

Not every difference between annotation and code is a problem. The annotation might be a high-level summary, and the code has implementation details. The auditor needs to distinguish between:

- **Acceptable abstraction** — "Manages session lifecycle" doesn't need to list every helper method.
- **Meaningful drift** — "Manages session lifecycle" but the module also routes messages. That's scope creep.
- **Dangerous omission** — "Does NOT handle persistence" but there's a `save_to_db()` method. That's a lie.

The prompting must teach the auditor to flag drift and omissions without drowning in noise from acceptable abstraction.

### 2. Structured output

The auditor's findings must be actionable, not vague. Each finding should specify:

- Which annotation
- What it claims
- What the code actually does
- Severity (drift vs. omission vs. naming)
- Suggested action (update annotation, refactor code, split module)

### 3. Scope of analysis

The auditor could analyze each annotation in isolation (cheap, fast) or analyze relationships between annotations (expensive, reveals more). Start with isolated analysis; cross-reference analysis is a future enhancement.

## Technical Shape

### How it runs

Option A: **Maintenance command** — `next-maintain` step, runs periodically.
Option B: **Standalone skill** — `/audit-code-context`, triggered on demand.
Option C: **Review phase integration** — part of `next-review`, checks annotations alongside code quality.

I think **Option B (standalone skill) first, Option C later**. The audit is a focused task that an agent can do in a single session. Making it a skill means any agent can invoke it anytime. Later, integrating it into the review phase makes it automatic.

### What it reads

1. All `code-ref/` snippets from `get_context(areas=["code-ref"])` — this gives annotations + metadata.
2. The actual source files referenced in each snippet's `source` frontmatter field.
3. The AST of the source files — to understand what the code actually does (public methods, imports, call patterns).

### What it produces

A structured audit report:

```markdown
# Code Context Audit Report

## Summary

- Annotations audited: 47
- Consistent: 39
- Drift detected: 5
- Omissions: 2
- Naming issues: 1

## Findings

### DRIFT: code-ref/core/output-poller

**Claims:** "Responsible for output capture ONLY"
**Reality:** Contains `format_for_telegram()` — formatting is an adapter concern.
**Severity:** Medium
**Action:** Move `format_for_telegram()` to the Telegram adapter.

### OMISSION: code-ref/adapters/telegram

**Claims:** "Telegram UI adapter that maps topics to sessions"
**Reality:** Also handles footer message lifecycle, download buttons, and MarkdownV2 escaping. None of these are mentioned.
**Severity:** Low (annotation is incomplete, not wrong)
**Action:** Expand annotation to include footer and formatting responsibilities.
```

### Where the report goes

- Written to `docs/project/audit/code-context-audit.md` (overwritten each run).
- Summary logged to console.
- Individual findings could optionally be promoted to `todos/` if severe enough.

## Implementation Shape

### The Audit Agent

This is an AI agent prompted to:

1. Read all code-ref snippets.
2. For each, read the actual source file.
3. Compare the annotation's claims against the code's behavior.
4. Produce structured findings.

The prompt needs to be precise about what constitutes drift vs. acceptable abstraction. The key heuristic: **if someone reading only the annotation would be surprised by what the code does, that's a finding.**

### The Skill

```
/audit-code-context
```

- Reads all code-ref snippets.
- For each snippet, reads the source file.
- Runs the comparison prompt.
- Produces the report.
- Optionally creates todos for severe findings.

### Data structures

```python
@dataclass
class AuditFinding:
    snippet_id: str
    finding_type: str  # "drift", "omission", "naming", "orphan"
    claims: str        # What the annotation says
    reality: str       # What the code does
    severity: str      # "high", "medium", "low"
    action: str        # Suggested remediation

@dataclass
class AuditReport:
    total: int
    consistent: int
    findings: list[AuditFinding]
    timestamp: str
```

### Cross-reference analysis (future)

Once isolated analysis works, the next level is cross-referencing:

- Build a responsibility graph from all annotations.
- Find overlaps (two modules claiming the same responsibility).
- Find gaps (responsibilities that no module claims).
- Find cycles (A depends on B, B depends on A, neither annotation mentions the other).

This is the "data lake" vision fully realized: the annotation corpus becomes a dependency graph that reveals architectural health.

## Prompting Draft: The Audit Prompt

This is the core of the auditor. The prompt must be precise.

```
You are auditing the consistency between code annotations and actual code behavior.

For each annotated element, you will receive:
1. The annotation (what the code claims to do)
2. The source code (what the code actually does)

Your job is to compare them and report inconsistencies.

## What IS a finding:
- The code does something the annotation doesn't mention (scope creep)
- The annotation says "does NOT do X" but the code does X (boundary violation)
- The code's naming doesn't match the annotation's described purpose
- The annotation is misleading — someone reading only the annotation would be
  surprised by what the code does

## What is NOT a finding:
- The annotation is a high-level summary and the code has implementation details
  (abstraction is expected)
- The code has private helper methods not mentioned in the annotation
  (internal implementation details are fine)
- The annotation doesn't list every parameter or return type
  (annotations are about responsibility, not signatures)

## The key question for each element:
"If an agent read only this annotation and then modified this code,
would the annotation guide them correctly or mislead them?"

If it would mislead them, that's a finding. If it would guide them
correctly (even if incompletely), that's consistent.

## Output format for each finding:
- snippet_id: the code-ref ID
- type: drift | omission | naming | boundary_violation
- claims: what the annotation says (quote the relevant part)
- reality: what the code actually does (cite specific methods/lines)
- severity: high (misleading) | medium (incomplete) | low (cosmetic)
- action: specific suggested fix (update annotation | refactor code | split module)
```

## Dependencies

- Requires Phase 1 (code-context-annotations) to be complete.
- Requires a meaningful number of annotations to be useful (seed annotations from Phase 1 Task 5 are the minimum).

## Open Questions

1. Should the auditor be an AI skill, a maintenance job, or both?
2. How deep should the code analysis go? (Public API only vs. full method-level analysis)
3. Should severe findings auto-create todos, or just report?
4. What's the minimum annotation coverage before the auditor produces value?
