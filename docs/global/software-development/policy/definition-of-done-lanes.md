---
description: 'The review lanes — the review-time enforcement of the Definition of Done. Defined once here; referenced by the build reviewer, the commit reviewer, and anticipated by the planner.'
visibility: 'public'
---

# Review Lanes — Policy

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/principle-violation-hunt.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/silent-failure-audit.md
- @~/.teleclaude/docs/software-development/policy/quality-predicate-registry.md

## Rules

The review lanes are the focus areas a code review runs. Each lane is the
**review-time enforcement of a Definition of Done gate** (or, for the scope lane,
the requirement contract). They are defined once here and consumed by:

- `software-development/procedure/lifecycle/work/review` — the build reviewer, which **executes** the applicable lanes.
- `software-development/procedure/lifecycle/work/review-commits` — the commit reviewer, which executes the same lanes minus scope.
- `software-development/procedure/lifecycle/prepare/plan-draft` and `.../prepare/review-plan` — the planner and plan reviewer, which **anticipate** the lanes (the plan must pre-satisfy what build-review will check).

Severity tiers, citation rules, the lane execution gate, and verdict arithmetic
live in the review procedure, not here — this catalog defines _what each lane
checks and the authority it answers to_, not how a review is run.

Run lanes in parallel where possible. Each lane produces findings with severity levels.

A project-scope testing ruling (for example a test moratorium) supersedes the
tests lane and every per-criterion named-test demand in Scope verification for
that project, per `general/policy/conflict-resolution`: reviewers there verify
each criterion against the evidence the project ruling sanctions (runtime
evidence such as restart and log-check records, code reading, review
reasoning) and treat demanding or rewarding forbidden test authorship as a
violation of the ruling, not diligence. All other lanes apply unchanged; in
every project without such a ruling this catalog applies in full.

| Lane                    | Reference                                                                              | Task                                                                                                                               |
| ----------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| scope                   | § Scope verification                                                                   | Verify delivery matches PRD intent — no gold-plating, no gaps                                                                      |
| code                    | § Code quality review; `code-quality-practices`, `design-fundamentals`                 | Find bugs and pattern violations                                                                                                   |
| paradigm                | § Paradigm-fit assessment                                                              | Check data flow, component reuse, pattern consistency, forward-migration of owned data                                             |
| principles              | § Principle violation hunt; `principle-violation-hunt`                                 | Structural violation hunt against design principles                                                                                |
| intelligence-boundaries | `principle/intelligence-boundaries`                                                    | Find code that classifies, scores, judges, or auto-edits free-text content semantics                                               |
| security                | § Security review                                                                      | Check for secrets, injection, auth gaps, and repository-privacy leakage                                                            |
| tests                   | § Test coverage check; `quality-predicate-registry`                                    | Evaluate behavioral value, weak-test anti-patterns, and coverage                                                                   |
| errors                  | § Error handling review; `silent-failure-audit`                                        | Find silent failures and inadequate error handling                                                                                 |
| types                   | § Type design review (when types added/modified)                                       | Validate type invariants, encapsulation, and enforcement                                                                           |
| comments                | § Comment accuracy review                                                              | Verify comments are accurate, non-stale, and earn their place                                                                      |
| logging                 | § Logging review                                                                       | Enforce logging policy; reject ad-hoc debug probes                                                                                 |
| docs                    | § Documentation and config surface check (when CLI, config, or API changed)            | Verify help text, config surface, README, and affected doc snippets reflect changes                                                |
| doc-hygiene             | § Doc-snippet hygiene (when a `docs/**` snippet or any directive-text surface changed) | Verify changed snippet bodies state present-tense contract — no narration; verify changed directive text was the author's to write |
| simplify                | § Simplification review (after other lanes pass)                                       | Simplify without behavior changes                                                                                                  |

### Lane coverage is reported in full — no silent skips

Lane coverage is a complete checklist, not a best-effort scan. The planner, the
plan reviewer, and the build reviewer each report **one line per lane in the
catalog above** — marking it satisfied (naming how), unmet (a finding), or `N/A`
(with reason). A catalog lane with no line is itself a defect: silence is not
coverage.

Deliverable-producing lanes (tests, security, docs, config, browser/UI, ADR) are
reported by naming the artifact and the task or diff that delivers it. The lanes
that produce no artifact — `code` Duplication, `paradigm` Component reuse, and
`simplify` — are reported against the changed surface itself: the plan's
`referenced-paths` at plan time, the diff at build time. A task or change that
re-derives, mirrors, or re-implements logic an existing symbol already provides,
instead of extracting it once and reusing it, is a duplication finding on this
checklist.

### Lane catalog

#### Scope verification

**Authority:** the requirement contract — `prd` (feature) or `input` (change/bug),
or the `implementation-plan`'s _Intent & scope_ for a `--plan` `change` with no `input`.

The delivery must match the approved intent (`prd` for a `feature`, `input` for a
`change`/`bug`, or the `implementation-plan`'s _Intent & scope_ for a `--plan`
`change` with no `input`; see `software-development/concept/approved-intent-artifact`) —
nothing more, nothing less.

For each approved-intent success criterion (a `prd` criterion, a goal/outcome stated in `input`, or — for a `--plan` `change` with no `input` — a goal/outcome stated in the `implementation-plan`'s _Intent & scope_), produce a `Scope verification` entry in `review-findings.md`:

1. Quote the criterion verbatim from the approved intent artifact.
2. Name the specific code change in the diff that delivers the criterion (file, function, line range).
3. Name the test whose passing demonstrates the criterion is delivered.
4. State, in one sentence, how the code change and the passing test together satisfy the criterion.
5. Name the concrete production-code mutation the named test kills — a single plausible wrong implementation of this criterion (a flipped condition, a dropped branch, a stubbed-out value) that turns the test red. Naming a real mutation is mandatory: it is the falsifiable proof that the test observes the criterion's actual property rather than a projection that cannot see it. If no such mutation exists — the test stays green on the broken implementation — that is the Requirement-Violation below, not a passing entry.

Findings:

- Criterion not delivered by any code change in the diff → **Requirement-Violation** (see Severity schema in the review procedure).
- Criterion partially delivered — some criteria sub-points addressed, others silently dropped → **Requirement-Violation**. A delivery that narrows a criterion's scope is as broken as one that omits it.
- Criterion delivered but the named test would pass even on a broken implementation → **Requirement-Violation**. Weak verification is not verification.
- Unrequested feature (no criterion drives it) → **Critical**.
- For a change/bug, a behavioral delta the intent does not call for — including one introduced alongside a necessary change, or one resolving a forced decision by new behavior where established behavior or human escalation was the path → **Critical**.
- Directive text authored where the intent called only for its removal or correction → **Critical**. Replacing an instruction the intent condemned with a different instruction of the author's own devising is a behavioral delta wearing the shape of the requested edit; the one-line diff and the honest commit subject are what let it pass. `general/policy/documentation-discipline` owns which text is directive.
- Gold-plating (scope creep beyond the PRD) → Important.

A reviewer cannot approve while any Scope verification entry is missing or names "none" for the code change, test, satisfaction analysis, or killing mutation.

#### Code quality review

**Authority:** DoD §2 (Code Quality) + `code-quality-practices`, `design-fundamentals`.

Systematically check changed code for bugs, pattern violations, and structural anti-patterns. Read `code-quality-practices` and `design-fundamentals` before starting.

For each changed file, evaluate:

1. **Bug detection** — Logic errors, null/undefined handling, race conditions, off-by-one errors, resource leaks. Focus on code paths that can produce wrong results or crash.
2. **Contract fidelity** — Do call sites honour the contract of the functions they call? Are preconditions met? Are return values handled correctly?
3. **Pattern violations** — Does the code follow the established patterns in adjacent code? Import conventions, error handling style, naming, module structure.
4. **Duplication** — Is logic copy-pasted where it should be extracted? Is an existing utility ignored?
5. **Unnecessary complexity** — Premature abstraction, over-engineering, dead code, unreachable branches, abstractions with a single consumer.
6. **Python string ownership** — Added or changed lines in non-test Python function bodies contain no inline string literals or literal f-string fragments. Findings cite the production call site and require the semantic owner defined by the Python core policy. Test inputs, fixtures, and test-local constants are outside this check; the tests lane judges their behavioral value.

Only report findings with high confidence — quality over quantity. Each finding must name the file, line range, the specific violation, and a concrete fix.

Severity guidance:

- Bugs that produce wrong results or crash → **Critical**.
- Contract violations at boundaries → **Critical**.
- Pattern violations that increase maintenance cost → **Important**.
- Unnecessary complexity or duplication → **Important**.
- Minor style inconsistencies that do not violate a cited policy → **drop the observation; it is not a finding**.

#### Paradigm-fit assessment

**Authority:** `design-fundamentals`, `backward-compatibility-hygiene`.

Check whether the implementation follows existing codebase paradigms:

1. **Data flow**: Does it use the established data layer, or bypass it with inline hacks?
2. **Component reuse**: Does it reuse and parameterize existing components, or copy-paste them?
3. **Pattern consistency**: Does it follow patterns established by adjacent code?
4. **Schema evolution**: For data the project owns (persisted state, config, artifacts), does it migrate the stored shape forward, or carry a backward-compatibility branch for an old shape? The contract for owned data is forward-migration (`backward-compatibility-hygiene`, Owned internal data); a version-tolerance branch in domain code is the violation, not the workaround. Any change to the field set of an owned persisted or serialized model — adding a field, renaming a field, removing a field, or tightening one to required — is itself a schema change: the diff must include the forward-migration step that rewrites existing records to the new shape **and** a golden-fixture test that loads an old-shape record through the new model. A field-set change with no migration is a defect that surfaces only when a pre-change record is read back, never in the change's own tests. The trap is a rename that does not bump the schema version: affected records are already stamped at the latest version, so a version-gated `vN → vN+1` hop never runs on them — the migration must normalize them unconditionally.

Paradigm violations are **Important** at minimum. Copy-paste of a parameterizable component is Important. Bypassing the data layer is Critical. A backward-compatibility branch on owned data — version tolerance smeared through domain logic where a forward migration is the contract — is Critical. A field-set change to an owned persisted or serialized model that ships with no forward-migration, or with no old-shape golden-fixture test, is **Critical** — it delivers a record the current model can no longer read.

#### Principle violation hunt

**Authority:** the documented design principles (`principle-violation-hunt`).

Systematic check of changed code against documented design principles, with fallback detection as the most prominent target. The reviewer performs this directly (not delegated) because it requires full context.

Use the `principle-violation-hunt` procedure for detailed hunt criteria.

**Severity baseline:** Unjustified fallback paths are **Critical**. A fallback is justified only when UX literally dies without it, documented in a code comment at the fallback site.

#### Intelligence-boundaries

**Authority:** `principle/intelligence-boundaries`.

Find code that classifies, scores, judges, evaluates, or auto-edits free-text
content semantics — intelligence that belongs in an agent's briefing, not in code
the agent wraps. Consult `principle/intelligence-boundaries` for the detection
patterns and the defining test.

#### Security review

**Authority:** DoD §5 (Security) + `security-awareness`.

Check the diff for security issues against the Definition of Done security gates:

1. **Secrets**: No hardcoded credentials, API keys, tokens, or passwords in the diff.
2. **Sensitive data in logs**: Log statements must not emit PII, tokens, or credentials.
3. **Input validation**: User input and external data validated at boundaries.
4. **Injection**: No command injection (f-string in shell calls), SQL injection, or template injection.
5. **Authorization**: Access control checks present where required.
6. **Error messages**: Stack traces and internal paths not exposed to end users.
7. **Repository privacy**: Inspect every changed text surface — including documentation,
   comments, examples, tests, fixtures, configuration samples, artifacts, and
   generated-looking files — for environment-derived computer or host names, usernames,
   internal addresses, absolute machine-local paths, session or transcript exports, debug
   dumps, or private topology. Operational documentation uses placeholders and points to
   the runtime discovery surface instead of copying current values.

Repository privacy is semantic reviewer judgment. Do not automate it with regex, keyword,
denylist, or other prose scanning; credential secret scanning remains a separate mechanical
control. Security violations are **Critical** findings.

#### Test coverage check

**Authority:** DoD §3 (Testing) + `software-development/policy/testing` and the per-language testing policy.

This lane applies the atomic rejection predicates in
`software-development/policy/quality-predicate-registry` and the doctrine in
`software-development/policy/testing` plus the relevant per-language testing
policy. The registry owns the rejection predicate and required evidence; the
testing policies own the behavioral model and language idioms. Read and apply
both; do not re-derive or restate either here.

This lane fires **always**, not only when test files changed. Read any changed or newly added tests directly and map each to the production behavior it claims to protect — never infer test value from file names, coverage output, or suite counts. The presence of tests is not evidence of adequate review.

Apply the policy, not a per-function reflex:

- **Coverage is the scenario inventory, not "every new function."** A coverage finding requires an **unbound feature-spec scenario this change delivers**. Absent such a scenario — platform-internal machinery, or a contract-defining / thin artifact (the artifact is its own spec) — there is nothing to bind, and "missing tests" is **not** a finding.
- **Never request an agent-authored unit test.** Where no compiler enforces unit-level correctness (Python, TypeScript) they are forbidden by policy. If branchy internal logic genuinely warrants coverage, the finding is to **extract it to a scenario-bound functional test** — never "add a test here."
- **Spec-delivered test specs:** every assertion from the spec-delivery commit must still exist; a removed or weakened assertion is a **Critical** finding (diff the spec-delivery commit against the final state).
- **Weak tests are findings even when coverage exists.** Apply every weak-test anti-pattern the testing policy enumerates — the policy owns the full list; do not re-list it here.
- **Browser / web UI changes** must include Playwright smoke evidence from build.

Before crediting any test as meaningful coverage, name the concrete production-code mutation it kills: a single plausible wrong implementation of the behavior under test — a flipped condition, a dropped branch, a stubbed-out value — that turns this test red. State it explicitly; a vacuous or unnameable answer ("it covers the feature") is itself the weak-test finding. A test that stays green on the broken implementation does not count, no matter what it asserts — the assertion is observing a projection of the output that cannot see the property the behavior actually changed.

- Reject **meta-tests that statically scan production source** (`ast.parse`, `rglob("*.py")` over `teleclaude/`, regex over file contents) to enforce a structural rule. A structural rule must be placed at the **strongest layer that can express it**, in this order — never lower when a higher one applies:
  1. **Make the illegal state unrepresentable** in the type/signature surface — an `Enum`/`StrEnum` for a closed vocabulary, a required parameter, a `NewType` — so the compiler / `pyright` rejects the violation at authoring time.
  2. **Native type checker / linter** (pyright, mypy, ruff) when a type can't make it unrepresentable but a native rule already covers it.
  3. **Custom `tools/lint/` guard** in `make lint` — **only** when 1–2 provably cannot express the invariant, and with a one-line justification of why no type/native check suffices.
  4. **Never** a runtime test for a static property.
     A test paying per-cycle cost for a static property — or a `tools/lint` guard duplicating what a type would enforce — is the anti-pattern, not the fix.
- Reject **placeholder or xfail "spec" tests** that document intended-but-not-yet-implemented behavior. The spec-anchored model has no waiting-to-flip tests: an unbound scenario is tracked as coverage backlog by the coverage tool, not as a test sitting in `tests/`. A test exists only to bind a scenario it currently satisfies. Also verify each binding is honest — it drives the real system for its scenario without mocking the thing under test — and that no in-scope spec has orphan or duplicate bindings (`tools/lint/spec_coverage.py` can be run on demand to surface these).

- Reject **an unreserved scenario binding** at plan-review anticipation. Every scenario a plan declares it will bind is reserved on `main` at prepare — enclosed by this todo's pending `planned` or `planned-change` marker. A plan that declares a binding for a scenario enclosed by a different in-flight todo's pending marker is a **Requirement-Violation**: the scenario is already reserved, and a second binding is the cross-worktree duplicate the integration content gate would otherwise catch. The check is structural — scenario id to owning slug — and `tools/lint/binding_reservation.py` surfaces the collisions on demand.

- Reject **refactor-leftover existence checks** — `assert not (_REPO_ROOT / "old_file.py").exists()` and shape variants. The git history records what was removed; the test adds nothing.
- Reject **filesystem-inventory snapshots** — `assert _inventory(some_root) == snapshot` where the snapshotted value is a dict/list of file paths produced by walking a directory tree. The snapshot pins the implementation's output layout, not behavior. If the behavior is "no files written to root X," assert emptiness directly: `assert not any(root.rglob("*"))`.

- Apply `TQ-04` from `software-development/policy/quality-predicate-registry` to configuration and default assertions. `TQ-04` is the single rejection predicate and evidence contract.

- Reject **unit tests wearing the `functional` label** — the `@pytest.mark.functional` marker is self-asserted by the author and proves nothing. A test fails this check when it enters at an internal symbol that is not the behavior's real surface and fakes that symbol's in-process collaborators (the classic "call the private `_step`, patch its neighbors"), or when it patches in-process non-boundary collaborators so the real chain never runs, or when its value is a return-value / construction-default / config-literal assertion. Verify against `software-development/concept/functional-test-boundary` that the test drives a real entry surface (CLI handler, route via a client, state-machine public driver, event bus, rendered widget) and fakes only the process or network line. A leading underscore is not the disqualifier — `_handle_blueprint_affected` is a real command boundary; an internal `_step_*` with its in-process neighbors patched is not. This is a review judgment against the definition; no path check or scanner decides it, and treating one as the enforcement manufactures false assurance.
- Reject **tests that pin a superseded owned-data shape** — a test asserting an old config, artifact, or persisted-aggregate schema the code is meant to migrate forward (`backward-compatibility-hygiene`, Owned internal data). It makes the dead compatibility path load-bearing and resists its own deletion. Schema-evolution coverage belongs in the migration's `vN → vN+1` golden-fixture test asserting the current shape — never in a test that locks the old one in place.
- Review snapshot deltas in the PR with the same weight as code deltas. Read each snapshot diff and confirm it matches the change's stated intent. An unreviewed or unjustified snapshot update is a finding.
- A test file appearing on the project's string-assertion exemption list is acceptable only if the current PR does not touch that file. If the PR touches a listed test file, the file must be migrated to snapshots in the same change and removed from the exemption list.

Treat the following as common weak-test patterns:

1. A test that only proves a string still reads the same.
2. A test that only proves an object still has fields visible in the source literal.
3. A test that only proves configuration, props, or data were passed through unchanged.
4. A test that only proves a primitive artifact or side effect exists after a direct library call.
5. A test that only proves a mock was called with the same data the test itself constructed.
6. A test that would stay green if the real branching logic were replaced with a constant or trivial passthrough.

Severity guidance:

- Weakening or deleting prepare-delivered spec assertions -> **Critical**.
- Missing tests for new or changed behavior -> **Important**.
- New or changed behavior covered only by weak tests -> **Important**.
- A changed test that cannot answer the "what bug would this catch?" question -> **Important**.
- A `functional`-marked test that drives an internal non-boundary symbol or fakes in-process collaborators so the real chain never runs -> **Important** (the coverage is illusory; **Critical** when it replaces or weakens a prepare-delivered spec assertion).
- Supplemental cleanup observations where a strong behavioral test already exists -> **drop the observation; it is not a finding**.

Missing tests for new behavior are **Important** findings.
Missing browser-smoke verification for browser-based frontend changes is an **Important** finding.

#### Error handling review

**Authority:** DoD §8 (Observability) + `silent-failure-audit`.

Audit all error handling paths in the diff for silent failures, inadequate logging, and inappropriate fallback behavior. Use the `silent-failure-audit` procedure for the systematic approach.

Key targets:

1. **Empty catch blocks** — absolutely forbidden.
2. **Broad exception catches** — `catch (Exception)` or `except Exception` that hide unrelated errors.
3. **Log-and-continue** — logging an error but continuing execution without surfacing to the caller.
4. **Silent defaults** — returning `[]`, `None`, `0`, or fallback values on error without logging.
5. **Optional chaining abuse** — `?.` chains that silently skip operations that should fail visibly.
6. **Retry without escalation** — retry loops that exhaust attempts without informing the caller or user.

For each handler, ask: would a developer debugging this 6 months from now have enough information in the logs to find the problem?

Severity guidance:

- Silent failures (error swallowed, no log, no user feedback) → **Critical**.
- Broad catches that could mask unrelated errors → **Critical**.
- Poor error messages or missing context in logs → **Important**.
- Unjustified fallback behaviour → **Important** (or **Critical** if it masks data corruption).

#### Type design review

**Authority:** DoD §2 (Code Quality) — type design.

When the diff introduces or modifies types, data models, or dataclasses, evaluate the type design quality.

For each type, assess:

1. **Invariant identification** — What consistency rules, valid state constraints, or relationship constraints does the type encode? Are they explicit or implicit?
2. **Encapsulation** — Are internals hidden? Can invariants be violated from outside the type?
3. **Invariant enforcement** — Are invariants checked at construction? Are all mutation points guarded? Can invalid instances be created?
4. **Usefulness** — Do the invariants prevent real bugs? Are they aligned with domain requirements?

Common anti-patterns to flag:

- Anemic domain models with no behaviour (just data bags with external logic).
- Types that expose mutable internals.
- Invariants enforced only through documentation, not code.
- Missing validation at construction boundaries.
- Types with too many responsibilities.
- **Closed vocabulary not modeled as the mandated type** — a finite set of related string values expressed as a `Literal` + scattered constants (or tuple/frozenset) instead of the single `StrEnum`/union `code-quality-practices` (State and Data) mandates, with literals inlined at call sites. The `Literal` permits the bare literal everywhere, which is precisely why a lint then has to police it. This lane fires on **production call sites**, never on a literal used as test input or fixture data; in a test the rule means importing the production member, not removing the literal — see `code-quality-practices` → Testing Alignment.
- **Invariant policed by a scanner a type could own** — an invariant enforced by an external lint, guardrail, regex, or meta-test when an `Enum`/type/schema could make the illegal state unrepresentable. The scanner is the band-aid; the type is the fix. See the enforcement-placement order in the test-coverage lane.

Severity guidance:

- Types that allow invalid states to be constructed → **Important**.
- Closed vocabulary as `Literal`+constants instead of `StrEnum` → **Important** (**Critical** when divergent inlined literals have already caused a defect).
- Invariant enforced by a lint/guard a type could make unrepresentable → **Important**.
- Exposed mutable internals on shared types → **Important**.
- Missing construction validation on boundary types → **Important**.
- Minor encapsulation improvements that do not violate a cited policy → **drop the observation; it is not a finding**.

#### Comment accuracy review

**Authority:** DoD §6 (Documentation) — comments.

Verify that comments on changed code are factually accurate, non-stale, and earn their place. A wrong comment is worse than no comment.

For each comment on changed code:

1. **Verify accuracy** — Cross-reference every claim against the actual implementation. Do described parameters, return types, and behaviour match the code?
2. **Check for staleness** — Does the comment describe the code as it was before this change, not as it is now? Stale comments after a refactor are a common source of confusion.
3. **Evaluate value** — Comments explaining "why" are valuable. Comments restating what the code obviously does are noise. Comments describing the past ("used to", "removed", "was previously") belong in git history, not in code.
4. **Flag misleading elements** — Ambiguous language, outdated references, assumptions that no longer hold, TODOs that are already done.

Severity guidance:

- Factually incorrect comments that will mislead future readers → **Important**.
- Stale comments that describe pre-change behaviour → **Important**.
- Commented-out code → **Important**.
- Redundant comments that restate obvious code → **Important** (per Comments policy: comments must earn their place; restating WHAT the code does is forbidden).

#### Logging review

**Authority:** DoD §8 (Observability) + the project logging policy.

Verify that changed code follows the project's logging policy. Load the language-appropriate logging policy for the project before reviewing.

Check for:

1. **Correct log levels** — INFO for business-relevant events, DEBUG for successful outcomes with duration, WARNING for recoverable anomalies, ERROR for failures. TRACE for high-volume chatter. Misleveled logs pollute or hide signal.
2. **Structured format** — Log statements must use structured key=value format through the project's logging framework, not f-string interpolation or print statements.
3. **Sensitive data** — Log statements must never emit passwords, tokens, API keys, PII, or entire payloads.
4. **Ad-hoc debug probes** — Print statements, console.log, or temporary logging added during development must be removed or converted to proper structured logs at the correct level.
5. **Identifier integrity** — Never truncate UUIDs or session IDs in logs. Full values only.
6. **Boundary coverage** — Key operations (API calls, state transitions, external service interactions) should have logging at entry or completion, not both (avoid start/end pairs; prefer one line with duration).

Severity guidance:

- Sensitive data in logs → **Critical**.
- Ad-hoc debug probes left in production code → **Important**.
- Wrong log levels that hide errors or pollute INFO → **Important**.
- Missing boundary logging for significant operations → **Important** (per DoD §8 Observability: logging at key boundaries is required).

#### Documentation and config surface check

**Authority:** DoD §6 (Documentation) + `documentation-first-development`.

When the delivery changes CLI subcommands, config keys, API endpoints, or user-facing behavior:

1. CLI help text updated for new/changed subcommands.
2. `templates/config.yml` updated if new config keys introduced.
3. Teleclaude-config spec updated if config surface changed.
4. README or relevant docs reflect current behavior.
5. Breaking changes documented.

**Doc-snippet reflection (always, not only interface changes):** when the delivery
changes or adds a documented behavioral contract, the corresponding doc snippet
(spec / principle / policy / concept / ADR) must be updated to match — as a pending
snippet (`delivered_by`) for lifecycle work, or directly for an in-place
correction. A behavioral delta whose contract snippet was not updated, with no
recorded `doc_impact_none: <reason>`, is a finding. This is the build/commit-review
backstop to the plan-review documentation hard gate, so a forgotten snippet update
cannot reach delivery.

**Work-phase doc freeze (build reviews only):** the doc layer is authored at
prepare on `main` and folded at integration; the work phase executes a frozen
contract. A lifecycle work-phase diff (slug worktree) that touches `docs/**` is
**Critical** — out of jurisdiction regardless of the edit's quality or size. The
correct route for a doc need discovered mid-build is the kickback path back to
prepare, never an in-worktree doc edit. This rule does not apply to commit
reviews of `main`-branch doc commits, which are prepare-side or in-context doc
work by design.

Missing documentation updates are **Important** findings. Missing config surface updates are **Critical** (agents depend on accurate config specs).

#### Doc-snippet hygiene

**Authority:** `general/principle/intent-first-documentation` + `general/policy/adr-discipline` + `general/policy/snippet-value-contract` (Narration anti-pattern) + `software-development/policy/process-change-authority`.

Conditional lane — fires whenever the diff touches a `docs/**` snippet **or any
directive-text surface** (below). The DoD docs lane above checks that docs _exist
and reflect the change_; this lane checks that the changed prose is _clean_ and
_the author's to write_. A snippet body states present-tense intent and contract —
nothing else. This is a reviewer judgment, not an automated grader: code that
scores free-text prose quality would itself violate
`principle/intelligence-boundaries`, so the reviewer reads the prose and applies
the rule. Tooling may **route** a diff into this lane by locating changed string
literals on the surfaces named below; it never grades what those literals say.

**Scope.** Audit the **changed regions** (added/modified lines and their enclosing
section), the snippet's **frontmatter**, and any **newly-added or delivered**
planned block (`&lt;!-- planned:slug --&gt;`), planned-change block
(`&lt;!-- planned-change:slug --&gt;`), or companion (`<stem>.<slug>.md`). Do NOT
re-audit unchanged regions of a snippet the diff merely touched elsewhere —
pre-existing narration outside the change is not this change's finding. A
delivered planned, planned-change, or companion body is fully in scope, because
delivery touches it.

**Co-tenant edits.** A diff may change a region enclosed by a different slug's
pending marker — a structural fact tooling may route on. Judge which edit it is.
_Aligning_ that slug's text with its own moved intent is legitimate: read that
slug's intent artifact and the diff, and ask only whether the edit preserves that
intent. Not its code, not its plan in full. _Superseding_ it — the changed text
becomes false when the editing slug delivers — must be attributable to the
editing slug and must not land ahead of it; an unattributed supersession folds
with the owning slug and ships a change its own review never saw.

**Directive-text surfaces.** Agent-facing directive text lives outside `docs/**`
as often as inside it, so this lane's trigger is the content, not the path. A
directive-text surface is any string a run of the system prints or hands to a
reader that names a next move: build-target and script output (`Makefile`,
`tools/**`), CLI help and error text, printed gate and guidance blocks, command
and skill bodies, and dispatched-worker briefs. `general/policy/documentation-discipline`
owns the directive-versus-descriptive cut; apply it rather than re-deriving one.
On these surfaces the narration anti-patterns below do not apply — they are
snippet-body rules — and two checks do:

- **Authorization.** The changed directive text is one the approved intent called
  for. Text authored where the intent called only for removal or correction is
  the `scope` lane's finding (below), raised there.
- **Process-change.** Directive text that alters a process-layer behavioral
  contract traces to a human decision per
  `software-development/policy/process-change-authority`.

**Frontmatter liveness check.** `delivered_by` is authorship provenance, not a
dispatch gate. The reviewer checks frontmatter shape and stale delivered
relationships against `project/spec/feature/context/snippet-frontmatter-validation`:
a known slug whose todo is already delivered is a finding, because delivery
should have folded it. A slug absent from the local todo store is not a finding:
todos are machine-local, so a git-carried pending snippet routinely names a
delivery that lives elsewhere or has already been hard-purged after reconciliation.
Do not use `telec todo show <slug>` 404 as evidence that a pending snippet is
undeliverable.

**Companion re-sync check.** When a commit edits a live parent `<stem>.md` and
a pending companion `<stem>.<slug>.md` exists, the reviewer reads both the
parent diff and the companion. The commit is flagged unless the companion is
re-synced in the same change or the diff records a deliberate coordination
decision. This is reviewer judgment over the changed files, not an automated
free-text grader.

**Process-change check.** When changed prose alters a process-layer behavioral
contract, flag it per `software-development/policy/process-change-authority`:
the change must trace to a human decision, and an agent-authored approval claim
in a human's name is itself a blocking finding. Descriptive edits that preserve
behavior do not trigger this check.

For each changed snippet body, flag the Narration anti-pattern in its four forms
(`snippet-value-contract` owns the full definition; do not re-derive it here):

1. **History in the body** — "replaces the v1 path", "is retired", "used to …",
   "previously named …". Belongs in git.
2. **Rationale in the body** — "because …", "this avoids …", "the reason we chose
   …". Belongs in the snippet's own Rationale section where its type has one, or is dropped.
3. **Inline provenance / coordination metadata** — "(delivered_by `<slug>`)",
   "Pending `<slug>`, …", a delivering slug named anywhere in body prose. Belongs
   in the `delivered_by` frontmatter field only.
4. **Future framing** — "will", "is planned", "the new surface is going to …",
   instead of a present-tense description of the intended shape.

When the changed snippet is an ADR (`docs/project/adr/**`), additionally hold its
body to the ADR contract (`general/policy/adr-discipline`, `general/procedure/adr-authoring`
— "What an ADR is"):

5. **Forward ADR reference** — the body references a _later_ ADR, a decision that
   did not exist when this one was recorded. A backward reference to an _earlier_
   ADR is fine; only the forward direction is the violation, and the sole forward
   link is `supersedes` frontmatter on the newer ADR.
6. **Work reference in an ADR** — the body names a todo, slug, `delivered_by`,
   delivery, or anything TBD, or the `adr` snippet carries a `delivered_by`
   frontmatter field or a companion file. An ADR records a decision, not work.
7. **Non-atomic ADR** — the record bundles more than one decision, or shards one
   cohesive contract across mutually-referencing ADRs (that contract belongs in a
   spec or domain doc).

Severity guidance:

- A **delivered** planned/companion body that carries future-framing or names its
  slug — now live and false in the standing contract → **Critical**.
- A forward ADR reference, or any work reference, in an ADR body → **Critical**
  (it falsifies the timeline or couples the record to ephemeral work).
- A non-atomic ADR, or a cohesive contract sharded across mutually-referencing
  ADRs → **Important**.
- Narration introduced or modified by this change in a live snippet body →
  **Important**.
- An edited parent snippet with an unsynced pending companion → **Important**.
- A snippet whose contract is correct but carries a stray rationale clause that belongs in its Rationale section or is dropped → **Important**.
- Pre-existing narration in a region this change did not touch → **drop the
  observation; it is not a finding** (the sweep owns it, not this review).

#### Doc-first paradigm check

**Authority:** `documentation-first-development`.

Conditional lane. Triggers only when the review surface is an ad-hoc commit series with no upstream prepare-phase artifacts (e.g. the Path C inline `/next-review-commits` dispatch flow). For lifecycle work reviews where a PRD, implementation-plan, and feature/domain spec are in context, the prepare phase already enforced the doc-first paradigm — this lane is a no-op there.

Consult `software-development/principle/documentation-first-development` for the authoritative Category A/B/C classification.

Apply the check only when the commit series shows clear Category A indicators:

- A new public agent verb in the `telec` surface.
- A new behavioral contract that spans multiple files and changes how agents are supposed to act.
- A new sealed guard / wrapper rule.
- A new event in the event taxonomy.
- A new bounded-context surface.

If at least one Category A indicator is present:

1. Inspect whether the series came through prepare (slug in commit subjects, `telec todo list --include-delivered` shows item, upstream prepare artifacts).
2. If it did NOT come through prepare, raise an **Important** finding: the series introduces what the principle classifies as Category A but bypassed the prepare phase where its feature spec snippet would have been authored.
3. The finding offers two acceptable resolutions:
   a. Author a retroactive feature spec under `docs/project/spec/feature/<context>/<concept>.md` and commit it as a Path A follow-up.
   b. Acknowledge the process gap explicitly in the report and defer retroactive authoring to the next prepare-phase pass that touches the same area.

Do NOT raise this finding for commits with no Category A indicators. Category B and Category C work legitimately produces no feature spec; the principle is the authority on classification — consult it rather than improvising.

#### Simplification review

**Authority:** `design-fundamentals` / KISS + naming-clarity policy.

Run after all other lanes pass. Simplify changed code for clarity, consistency, and maintainability without changing behaviour.

Focus on:

1. **Unnecessary complexity** — Reduce nesting depth, eliminate redundant branches, flatten deeply nested conditionals.
2. **Redundancy** — Remove duplicate logic, consolidate related operations, eliminate dead code.
3. **Naming** — Improve variable and function names that don't communicate intent.
4. **Over-abstraction** — Remove abstractions with a single consumer. Three similar lines are better than a premature abstraction.
5. **Clarity over brevity** — Avoid nested ternaries; prefer explicit if/else or switch. Explicit code beats compact code.

Constraints:

- Never change what the code does — only how it does it.
- Do not combine too many concerns into single functions.
- Do not remove helpful abstractions that improve organisation.
- Scope to recently changed code unless explicitly instructed otherwise.

Simplification findings are **Important** severity. The simplify lane only flags concrete violations of KISS, design-fundamentals (over-abstraction, dead code), or naming-clarity policy — those are real maintainability concerns and they affect the verdict. If an observation cannot be tied to one of those policies, drop it; it is not a finding.

#### Bug-fix review

**Authority:** DoD §3 (Testing) + `debugging`. Conditional lane — fires when `kind == "bug"`.

When `kind == "bug"`, the `input` artifact is the bug report and the intent source (no `prd`),
sharpened by the `diagnosis` root cause. Verify:

1. Fix addresses the symptom described in `input`.
2. Root cause analysis is sound.
3. Fix is minimal and targeted: the smallest change that removes the diagnosed root cause, plus the
   verification proving the symptom gone — and **nothing else**. A delta that removes no part of the
   cause and proves nothing gone — hardening, extra validation layers, defensive defaults, fallbacks,
   adjacent refactors, new capability — is a **Critical** scope finding, even when the approved plan
   contains it: for a bug, `input` + `diagnosis` outrank the plan as scope authority.
4. Investigation and documentation sections are complete.
5. A reproduction test exists — the bug was reproduced as a test before the fix — binding either a
   pre-existing scenario or the single regression scenario the plan phase authored for this symptom
   (`policy/testing` rule 2, bug-lane exception) — unless the fix is a contract-defining artifact
   with no bindable scenario (see `software-development/policy/testing`, "Contract-defining artifacts
   are not tested"), in which case there is correctly no test.
6. The reproduction test passes after the fix (when item 5 requires one).
7. No scenario beyond the single regression scenario was authored, and beyond that scenario no new
   contract text shipped unless the diagnosed cause is a wrong documented contract — a fix that
   restores documented behavior carries `doc_impact_none`.

Missing reproduction test for a bug fix is a **Critical** finding **only when a bindable scenario
exists**. Demanding a test for a fix that is itself a declaration is the error, not the missing test.
All other review lanes still apply.

**Record-drift exception to item 2.** "Root cause analysis is sound" is not
Critical when all three hold at once:

1. The delivered code already satisfies every criterion in `input` — Scope
   verification is clean, nothing is left to build.
2. The only defect is that `diagnosis`/`investigation`/`implementation-plan`
   describe stale reality — a factual claim about what already happened (a
   root cause, a "this passes at HEAD" claim), not a wrong claim about what
   should have been built. Nothing about the approach was wrong.
3. Correcting the record implies no new functional or business decision — a
   rewrite of a description, not a re-derivation of intent.

When all three hold, the discrepancy is not Critical, does not force `REQUEST
CHANGES`, and its remedy is not kickback — record it as a `log` entry on the
todo (`project/spec/domain/workflow`) instead: a factual note, never a
substitute for a real finding. Fail any one condition and this is a normal
finding at full severity: a root cause that is actually wrong — even when the
shipped fix happens to pass — does not qualify, nor does a fix that took a
wrong approach and merely happens to work. This is a narrow, checkable
exception for when delivery is already correct and only the trailing record is
wrong about it, not a general softening of root-cause rigor.

## Rationale

The lanes were embedded in the build-review procedure and re-described in the
plan reviewer, so two reviewers shared one copy and a third forked it — the lane
set could drift between "what the plan anticipates" and "what build-review
checks." Defining the lanes once, here, and having every reviewer and the planner
reference this catalog removes that drift.

Anchoring them under the Definition of Done makes the coupling explicit: each lane
is the review-time enforcement of a DoD gate (or the requirement contract for
scope). A new DoD gate should grow a lane; a lane should name the gate it answers
to. The per-lane **Authority** line is that binding, kept honest in one place.

## Scope

Applies to build reviews, commit reviews, and prepare-plan review anticipation.

## Enforcement

Reviewers use this catalog as the lane inventory. Procedure snippets own execution
mechanics, verdict arithmetic, and report shape.

## Exceptions

None.
