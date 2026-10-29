---
description: 'Practical guidance for applying code-quality policy in day-to-day work.'
visibility: 'public'
---

# Code Quality Practices — Policy

## Rules

### Structure and Responsibility

- Follow the repository's configuration and established conventions.
- Introduce new patterns only when required by the intent (**YAGNI**).
- **SRP**: each module, function, or class has one reason to change. If a description requires "and," split it.
- Separate core logic from interfaces and operational concerns (**Separation of Concerns**).
- Prefer designs that are explicit, verifiable, and easy to reason about (**KISS**). Essential complexity is justified; accidental complexity is not.
- Group by domain concern, not by technical category (**High Cohesion**). No `utils` or `helpers` modules.
- Build complex behavior by combining simple pieces, not by extending class hierarchies (**Composition over Inheritance**).

### Dependencies and Boundaries

- High-level modules define shapes; low-level modules implement them (**DIP**). Core never imports from adapters.
- Pass dependencies through parameters or constructors (**Loose Coupling**). Do not import singletons.
- Only talk to immediate collaborators, not to their internals (**Law of Demeter**). Prefer one dot over a chain.
- Make contracts explicit and enforce invariants at boundaries.
- Preserve signature fidelity across all call chains.

### State and Data

- Use structured models to make illegal states unrepresentable.
- Assign explicit ownership to state and its lifecycle (**Encapsulation**).
- Default to immutable data. Keep mutable state in a single owner (**Immutability Preference**).
- Avoid implicit global state or import-time side effects.
- **The process environment is not an in-process configuration or state channel.** Deployment-time environment is read exactly once, at a single typed, immutable configuration seam; in-process code reads configuration through that seam, never from the environment directly, and never mutates the environment to change its own behavior. Setting the environment for a child process you spawn is the one allowed write — that is the child's startup seam, not in-process state.
- A fixed set of related identifiers (states, modes, tab/section names, dispatch keys) is owned by one named, namespaced closed type and referenced by member — never inlined as a literal at call sites. Inlined copies drift (casing, typos) and make illegal states representable. The applicable language policy owns the concrete representation.
- **A runtime string gets a named owner only when it is shared knowledge** (**DRY**): the same value is used in more than one place, or another module consumes it. It is then declared once, in the module that owns its meaning, and every user imports it. A string with a single use stays inline where it is used. A constant that names one use — an empty string, a message one log call writes, a path one request sends — removes no duplication, adds a hop for every reader, and is a finding. Language policies define where an owner is declared. Test inputs and fixtures follow the testing policy and do not acquire production ownership merely by being moved into test-local constants.
- **Enforce an invariant at the strongest layer that can express it**, in order: ① make the illegal state unrepresentable in the language's type system; ② use a native type checker or linter rule; ③ add a custom lint or guard **only** when ①–② provably cannot express it, with justification; ④ never use a runtime test for a static property. An invariant a type can express is enforced **by the type** — reaching for a lint, guardrail, regex, or meta-test to police what the type would make unrepresentable is the **lint-as-type-substitute** anti-pattern. It is also a separation-of-concerns violation: domain vocabulary (the values and their canonical owner) lives in the type, never embedded in generic tooling.

### Duplication and Abstraction

- Extract shared **knowledge** to a single owner (**DRY**). Same business rule in two places will diverge.
- Tolerate duplicated **code** when the alternative couples unrelated domains. Duplication is cheaper than the wrong abstraction.
- Do not create abstractions for patterns that occur once (**YAGNI**). Wait for a second real consumer.

### Presentation and Enrichment

- Build presentation from established records and prepared display facts, trusting their owning contracts. Resolve missing display facts in the presentation-enrichment owner before rendering.
- Reuse expensive presentation-only lookups across records and renders through a cache owned by the enrichment helper or service. Keep source-loading primitives under their existing validation and freshness contracts; cheap pure formatting remains direct.
- The cache owner defines its identity and scope keys, source dependencies, invalidation, freshness, and cold-load or refresh-failure behavior. Source changes invalidate dependent facts, including cached misses, through the existing change-notification path where available. Any TTL follows the display facts' freshness needs and supplements invalidation.
- Prepare expensive display facts outside rendering and serialization loops. Keep blocking source reads and freshness checks off shared event loops on cold loads and refreshes as well as cache hits. Concurrent refreshes publish only values whose dependencies remain current after invalidation.

### Error Handling and Recovery

- Fail fast on contract violations with clear diagnostics.
- Inside an operation, catch the specific failures the code can act on; every other failure propagates to the boundary that owns the operation.
- **A supervision boundary contains every failure of the unit it runs.** The top of a loop or long-lived task that serves independent units of work — a message or request intake, a queue or stream consumer, a scheduler tick, an event dispatcher — catches any failure of one unit, logs it with its stack trace, answers that unit's caller with an error where the unit has one, and continues with the next unit. A programming error crashes its unit, never the loop. Cancellation and shutdown signals still propagate through it.
- **A long-lived task the process depends on is supervised.** When it ends unexpectedly, its supervisor logs the end and restarts it, or terminates the process so its service manager restarts it.
- Keep recovery logic explicit and minimal.
- Make error posture clear: when to stop, when to continue, and why.
- Validate at system boundaries; trust within (**Fail Fast** at boundaries, not everywhere).

### Concurrency

- Preserve deterministic outcomes under concurrency.
- Aggregate parallel work explicitly and keep ordering intentional.
- Protect shared state with explicit ownership or isolation.
- Hold a shared resource only around the work that needs it, and bound every wait for one. A caller with a deadline receives its outcome, done or refused, within that deadline.

### Observability

- Log boundary events and failures with enough context to diagnose.
- Prefer clarity over volume; log what changes decisions.

### No Shell-Outs from Application Code

- Use the language's native APIs and project helpers for all operations — filesystem, git, network, process management.
- Do not invoke shell commands or child processes when a native or project-provided API exists.
- The only escape hatch: the operation requires an external binary that has no language binding or project helper. In that case, the call **must** include a comment justifying why a native approach is not viable.
- Reviewers **must reject** any shell/process invocation that lacks this justification.

### Naming and Comments

- Name for semantics, not origin. Names must make sense to someone who never saw the feature request or ticket that motivated the change.
- Comments describe the present, never the past. No "removed X", "used to do Y", "added for Z", and no reference to the bug, ticket, incident, or motivation that prompted the code. Git history and ADRs own the "why it changed"; comments explain what is here now.
- Comments and docstrings do not restate policy or shared rules. Describe what the code is; the policy is the single owner of the rule — reference it if needed, never duplicate it.
- **Prose may name the owner of a runtime or configuration value; it never repeats the value.** Numbers, durations, limits, thresholds, ports, paths, defaults, cadences, retention windows, current enum members, configured services, registry contents — anything whose canonical value lives in code, configuration, schema, or a runtime registry. The copy goes stale the moment the value moves, and a reader who finds two answers cannot tell which is authoritative. Forbidden: `Soft-removed todos purge after 7 days.` Allowed: `Removed-todo retention is owned by REMOVED_TODO_RETENTION_WINDOW.` Prose explains purpose, invariants, ownership, and where to look; the declaration states the value once. A comment sitting beside the constant it describes is the clearest case: it has nothing to add by repeating it.
- When removing code, remove it completely. No `_unused` renames, no `// removed` comments, no re-exports for backward compatibility unless explicitly required.

### Testing Alignment

- In tests, assert observable behavior and contracts, not narrative documentation wording.
- String content is asserted via snapshots, never literal/substring/pattern comparison. Protocol identifiers go through named constants whose values are snapshot-governed at the schema layer. See `sdlc/policy/testing` → "String Assertions — One Paradigm".
- The closed-vocabulary rule (State and Data) governs production **call sites**, where an inlined literal drifts and makes illegal states representable. In a test it means importing the production member when behavior turns on its identity — never that a fixture literal must be lifted out of the test body. "Extract this test string into a constant" is not a sanctioned remedy; the test-side owner is the string-assertion paradigm above (snapshot, or imported production member).

## Rationale

Apply the code-quality policy and design principles consistently in daily work. Named principles provide shared vocabulary for structural reasoning; these rules translate them into concrete habits.

A loop that serves independent callers shares its fate across all of them: whatever ends it denies service to every later caller while the process still looks alive. A closed list of failure types reflects only the types that existed when it was written, so a loop guarded by one stays available only as long as no code it runs ever gains a new failure type. A task that has died inside a live process is invisible to the service manager that would otherwise restart it.

A string's owner exists so its knowledge lives in one place: two copies of one value drift apart, and a consumer that imports the owner shows the dependency to readers and to import-graph and blast-radius tooling. A string used once has no second copy to drift and no consumer to trace, so naming it buys neither and costs every reader a lookup.

A lock, transaction or queue shared with unrelated work makes its holders' durations part of every waiter's latency. Taken on a path many sessions call, it charges each caller the longest concurrent holder — a commit's quality gate, an integration push — and an unbounded wait stretches that past the caller's deadline, so work that succeeds is reported as failed. Protection is visible in the code that takes the resource; its cost is visible only in who else holds it, which is why the bound and the deadline are stated alongside the protection.

Presentation repeats as records multiply and views redraw. Source discovery or validation hidden inside a display helper makes that cost part of every render and can stall unrelated work sharing its event loop. Caching at the enrichment owner preserves the source contract while reusing display facts; explicit dependencies and invalidation keep those facts coherent when their sources change.

## Scope

Applies to all code in the repository.

## Enforcement

Violations should be fixed before merge; reviewers enforce this policy.

## Exceptions

None. If a deviation is required, document the rationale and get explicit approval.
