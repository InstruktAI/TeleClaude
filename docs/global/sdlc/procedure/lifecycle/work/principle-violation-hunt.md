---
description: 'Hunt for code that violates documented design principles. Surface structural issues that a surface review would miss.'
visibility: 'public'
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

**Aliases:** A fallback rarely names itself. "Hardening", "graceful degradation", "defensive default", "safety net", "best-effort recovery", and "tolerant parsing" are the usual labels — judge the mechanism (a substitute path taken when the primary fails or input is bad), not the label. A renamed fallback is still a fallback and carries the same severity.

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

### 3a. Domain Ownership

- A domain rule implemented in the caller, adapter, scheduler, daemon, shared
  utility, persistence host, or current file instead of the context that owns
  its meaning and reason to change.
- A consumer restating, specializing, validating, defaulting, recovering, or
  mutating policy that belongs to another context.
- Correct architectural-layer placement inside the wrong bounded context.
- A cross-cutting coordinator, design surface, or shared module becoming the
  sole home of a participating context's invariant.
- A direct dependency that bypasses the owner's published command, query,
  event, or type.

**Severity:** Critical. Existing placement and adjacent pattern consistency do
not mitigate wrong ownership; they may be the defect being repeated.

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
- Mutable records passed across module boundaries.

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

### 10. Enforcement in the wrong layer

A structural invariant policed by a lint, guardrail, regex, or meta-test that
a type or schema could make **unrepresentable**. The fix is to move the
invariant up to the strongest layer that can express it (see the
enforcement-placement order in `definition-of-done-lanes` → test-coverage lane),
not to add the scanner.

Patterns to detect:

- A closed or finite vocabulary modeled through permissive aliases and scattered
  constants instead of the closed type mandated by the applicable language
  policy, followed by a lint that forbids the literals the representation permits.
- A runtime assertion, source scan, or custom lint guard that re-checks a property
  a required parameter, nominal type, or closed type would reject statically.
- Domain vocabulary (the allowed values, the canonical module path) hard-coded
  into a generic tooling/lint script rather than owned by the domain type.

**The defining test:** would this lint/guard/test be unnecessary if the type
made the illegal state impossible to write? If yes, the enforcement is in the
wrong layer — the type is the fix, the scanner is the band-aid.

**Severity:** Important — **Critical** when the scanner has been added in place
of a type the applicable language policy already mandates.

## Outputs

- Issue list per category with severity, location, principle violated, and remediation guidance.
- Unjustified fallbacks are always escalated to Critical in the review findings.

## Recovery

- If scope is too large for a single pass, prioritize by blast radius: fallback/silent-degradation first, then DIP violations, then the rest.
- If a pattern is ambiguous (could be justified), flag it as Important with a note requesting explicit justification.
