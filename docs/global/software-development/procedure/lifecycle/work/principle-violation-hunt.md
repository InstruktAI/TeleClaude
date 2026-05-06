---
description: 'Hunt for code that violates documented design principles. Surface structural issues that a surface review would miss.'
id: 'software-development/procedure/lifecycle/work/principle-violation-hunt'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Principle Violation Hunt — Procedure

## Goal

Hunt for code that violates documented design principles. Surface structural issues — silent degradation, coupling violations, responsibility sprawl — that a surface-level review would miss.

## Preconditions

- Changed files are available (diff or worktree).
- The reviewer has loaded `design-fundamentals` for anti-pattern vocabulary.

## Steps

Work through each category below against the changed code. For each violation found, report: location (file:line), severity, principle violated, and what the code should do instead.

### 1. Fallback & Silent Degradation (Critical focus)

This is the highest-priority category. Unjustified fallbacks are **Critical** findings.

**Patterns to detect:**

- **Return-default on failure** — `return []`, `return None`, `return {}`, `return first_match` where the caller expects valid data and failure would be more correct.
- **Lookup with fallback resolution** — A function that looks up X, fails, then silently tries a different lookup path and returns that instead. The caller believes it got X; it got Y.
- **Broad exception catches** — `except Exception`, `except BaseException`, bare `except:`, `catch (Error)`, `catch (*)`. These hide unexpected failures behind expected-error handling.
- **Log-and-continue** — Catching an error, logging it, and continuing execution without surfacing the failure to the caller.
- **Silent default substitution** — A function receives `None` or missing data for a required parameter and substitutes a default instead of raising.

**Severity:** Critical unless the code has an explicit comment explaining why UX requires the fallback.

**Justification standard:** "The user experience literally dies without this fallback" — convenience, robustness-theater, and "just in case" are not justification. A code comment must explain the specific UX failure that the fallback prevents.

### 2. Fail Fast

- Defensive checks deep inside trusted code paths (validate at boundaries, trust within).
- Preconditions that silently pass instead of asserting.
- Functions that accept invalid input and attempt to "make it work" instead of rejecting.

**Severity:** Important.

### 3. Dependency Inversion (DIP)

- Core modules importing from adapter packages.
- Adapter-type branching in core code (`if adapter == "telegram"`).
- High-level modules depending on low-level implementation details.

**Severity:** Critical at architectural boundaries, Important elsewhere.

### 4. Coupling & Law of Demeter

- Multi-dot chains reaching through object internals (`a.b.c.d`).
- God object dependencies — many modules importing the same mutable singleton.
- A module that breaks when an unrelated module changes.

**Severity:** Important for deep chains, Critical for god-object patterns.

### 5. Single Responsibility (SRP)

- Functions doing multiple unrelated things (description requires "and").
- Classes accumulating responsibilities beyond their original purpose.
- Modules mixing domain concerns (e.g., business logic and transport).

**Severity:** Important.

### 6. YAGNI / KISS

- Premature abstractions — base class/interface/utility for a pattern that occurs once.
- Configurability for a single consumer.
- Generic factories or dispatch tables where a direct call or simple conditional works.

**Severity:** Important. The hunt only flags premature abstractions, single-consumer
configurability, and accidental complexity that violates KISS or YAGNI — those are
real maintainability concerns. If the observation cannot be tied to a cited
principle, drop it; it is not a finding.

### 7. Encapsulation

- External code directly reading/writing internal state or private fields.
- Anemic domain models — objects that are data bags with all logic in external functions.
- State mutations without validation (e.g., `session.status = "active"` instead of `session.activate()`).

**Severity:** Important.

### 8. Immutability

- Functions mutating their input arguments.
- Shared mutable state accessed by multiple callers or coroutines.
- Mutable dataclass fields passed across module boundaries.

**Severity:** Important for shared state mutation. Local mutation that does not
violate the immutability-preference policy is not a finding — drop the observation.

### 9. Intelligence in the wrong layer

Per `principle/intelligence-boundaries`. Code performing classification,
scoring, judgment, evaluation, or auto-editing of content semantics — work
the agent layer should do.

Patterns to detect:

- Hardcoded vocabulary tables for content categorization (`_ACK_*`,
  `_KEYWORDS`, `_HINTS`, `_PHRASES`).
- Regex on free text driving semantic decisions ("is this meaningful?",
  "is this an ack?", "is this idle chatter?").
- Word-count thresholds for "is this important?" / "is this actionable?".
- Predicates on natural language: `is_meaningful`, `should_emit`,
  `is_actionable`, `is_ack`, `classify_*` on free-text payloads.
- Auto-fixers that rewrite agent artifacts to match structural rubrics
  (regex section-header grading then regex-driven section insertion).
- Structural-rubric grading via regex on document headers / formatting
  ("documents with `## Goal` and `## Acceptance` score higher").

**Severity: Critical.** This pattern accumulates and corrupts the codebase
faster than coupling violations because every implementation looks
"well-typed and narrow." The defining test: would this code be unnecessary
if the agent's briefing said the right thing? If yes, it's policy in the
wrong layer.

## Outputs

- Issue list per category with severity, location, principle violated, and remediation guidance.
- Unjustified fallbacks are always escalated to Critical in the review findings.

## Recovery

- If scope is too large for a single pass, prioritize by blast radius: fallback/silent-degradation first, then DIP violations, then the rest.
- If a pattern is ambiguous (could be justified), flag it as Important with a note requesting explicit justification.
