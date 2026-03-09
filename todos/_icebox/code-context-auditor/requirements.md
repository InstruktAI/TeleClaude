# Code Context Auditor — Requirements

## R1: Audit Scope

### R1.1: Input Sources

- All `code-ref/` snippets from the context index (via `get_context` or direct index read).
- The actual source files referenced in each snippet's `source` frontmatter field.
- AST analysis of source files to understand public API surface, method responsibilities, imports.

### R1.2: Analysis Depth

- **Isolated analysis** (Phase 2a): Each annotation compared against its own source file.
- **Cross-reference analysis** (Phase 2b, future): Annotations compared against each other for overlaps, gaps, and dependency consistency.

### R1.3: Finding Types

| Type                 | Meaning                                                         |
| -------------------- | --------------------------------------------------------------- |
| `drift`              | Code does things the annotation doesn't mention (scope creep)   |
| `omission`           | Annotation is missing significant responsibilities the code has |
| `boundary_violation` | Annotation says "does NOT do X" but the code does X             |
| `naming`             | Code naming doesn't match annotation's described purpose        |
| `orphan`             | Significant code with no annotation (coverage gap)              |

### R1.4: Severity Levels

| Severity | Criterion                                                  |
| -------- | ---------------------------------------------------------- |
| `high`   | The annotation would mislead an agent modifying this code  |
| `medium` | The annotation is materially incomplete but not misleading |
| `low`    | Cosmetic or minor inconsistency                            |

## R2: The Audit Prompt

### R2.1: Core Heuristic

The auditor's key question: **"If an agent read only this annotation and then modified this code, would the annotation guide them correctly or mislead them?"**

- Misleading → finding (high severity)
- Correct but incomplete → finding (medium severity) if the missing info could cause mistakes
- Correct at the right level of abstraction → consistent (no finding)

### R2.2: What Counts as Consistent

- High-level summary covering the main responsibility.
- Private implementation details not mentioned (internal helpers, caching, etc.).
- Parameters, return types, error handling details not listed (annotations are about responsibility, not signatures).

### R2.3: What Counts as Inconsistent

- Code performing responsibilities outside the declared scope.
- Explicit boundary statements violated ("does NOT do X" but code does X).
- Module naming that contradicts the declared purpose.
- Significant public API surface not reflected in the annotation.

### R2.4: Prompt Calibration

The prompt must be tested against known-good and known-bad annotation/code pairs to verify:

- It doesn't flag acceptable abstractions as drift.
- It does catch genuine scope creep.
- It does catch boundary violations.
- Severity ratings are consistent across similar findings.

## R3: Output Format

### R3.1: Audit Report

Structured markdown report written to `docs/project/audit/code-context-audit.md`:

```markdown
# Code Context Audit Report

**Date:** 2026-02-09
**Annotations audited:** 47
**Consistent:** 39
**Findings:** 8

## Findings

### DRIFT: code-ref/core/output-poller

**Claims:** "Responsible for output capture ONLY"
**Reality:** Contains `format_for_telegram()` — formatting is an adapter concern.
**Severity:** Medium
**Action:** Move `format_for_telegram()` to the Telegram adapter.
```

### R3.2: Machine-Readable Output

In addition to markdown, produce a structured data file (`audit-results.json`) for tooling consumption:

```json
{
  "timestamp": "2026-02-09T14:30:00Z",
  "total": 47,
  "consistent": 39,
  "findings": [
    {
      "snippet_id": "code-ref/core/output-poller",
      "type": "drift",
      "claims": "Responsible for output capture ONLY",
      "reality": "Contains format_for_telegram()",
      "severity": "medium",
      "action": "Move format_for_telegram() to the Telegram adapter"
    }
  ]
}
```

### R3.3: Coverage Report

Alongside findings, report annotation coverage:

- Total Python files in configured source directories.
- Files with at least one annotation.
- Coverage percentage.
- List of large (>100 LOC) unannotated files as coverage gap candidates.

## R4: Execution Model

### R4.1: Skill

A standalone skill `/audit-code-context` that any agent can invoke:

- Reads the annotation corpus.
- Reads source files.
- Runs the audit prompt per annotation.
- Produces the report.
- Logs summary to console.

### R4.2: Maintenance Integration (Future)

Once the skill is stable, integrate into `next-maintain`:

- Run the audit as a periodic maintenance step.
- Auto-create todos for high-severity findings.
- Track finding trends over time.

## R5: Agent Prompting

### R5.1: The Auditor's Identity

The auditor is prompted as a code reviewer focused on annotation accuracy. It is not criticizing the code — it's verifying that the documentation contract matches reality. Frame it as a health check, not a judgment.

### R5.2: Evidence-Based Findings

Every finding must cite specific code evidence:

- Method names, class members, import statements.
- Line references when relevant.
- Not vague ("the code seems to do more") but specific ("contains `save_to_db()` method not mentioned in annotation").

### R5.3: Actionable Suggestions

Every finding must suggest a specific remediation:

- "Update annotation to include footer management responsibility"
- "Move `format_for_telegram()` to the Telegram adapter module"
- "Split `MessageOps` into delivery and formatting concerns"

## R6: Dependencies

- Requires `code-context-annotations` (Phase 1) to be complete.
- Requires seed annotations (Phase 1, Task 5) as minimum input.
- Produces value proportional to annotation coverage; recommend 20+ annotations before first meaningful audit.
