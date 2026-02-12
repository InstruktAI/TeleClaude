---
description: 'Named design principles for structural decisions. SRP, DIP, DRY, KISS, YAGNI, coupling, cohesion, composition, encapsulation, Demeter, fail fast, immutability.'
id: 'software-development/principle/design-fundamentals'
scope: 'domain'
type: 'principle'
---

# Design Fundamentals — Principle

## Principle

Good design emerges from a small set of named forces applied consistently: keep responsibilities singular, dependencies inverted, knowledge local, and complexity proportional to the problem.

## Rationale

Without shared vocabulary for structural reasoning, code review devolves into taste arguments and agents cannot distinguish principled design from accidental complexity. Named principles give a shared language for identifying problems and justifying decisions.

## Implications

### SRP — Single Responsibility Principle

Every module, function, or class has **one reason to change**. If a description requires "and" — it does too much.

- **Recognize it:** A function that checks existence, creates a resource, retries on failure, updates the database, and returns a result has five responsibilities.
- **Apply it:** Extract each concern into its own function. The orchestrating function composes them.
- **Anti-pattern: "God function / god class"** — modules that accumulate responsibilities because they were convenient to extend.
- **Bend it:** Trivial operations (log + return) don't need separate functions. SRP targets _reasons to change_, not _lines of code_.

### DIP — Dependency Inversion Principle

High-level modules define the shapes they need. Low-level modules implement those shapes. Neither depends on the other's internals.

- **Recognize it:** Core models importing adapter-specific types. Core code checking `if adapter == "telegram"`.
- **Apply it:** Core defines a protocol or abstract shape. Adapters conform to it. Core never imports from adapters.
- **Anti-pattern: "Leaky abstraction"** — implementation details of a lower layer force changes in a higher layer.
- **Bend it:** In a monolith, strict inversion at every seam adds ceremony. Apply it at architectural boundaries (core/adapter, core/transport), not between every internal module.

### DRY — Don't Repeat Yourself

Every piece of **knowledge** has a single, authoritative representation. When the same business rule exists in two places, they will inevitably diverge.

- **Recognize it:** The same validation logic in both an API handler and a database layer. The same config parsing in three adapters.
- **Apply it:** Extract the shared knowledge to its single owner. Reference it from consumers.
- **Anti-pattern: "Shotgun surgery"** — a single change requires editing many files because the same knowledge is scattered.
- **Critical nuance:** DRY applies to **knowledge**, not to **code that looks similar**. Two functions with identical syntax but different _reasons to exist_ are not duplication — they serve different domains. Forcing them to share an abstraction couples those domains. **Duplication is cheaper than the wrong abstraction.**

### KISS — Keep It Simple, Stupid

The right solution is the simplest one that meets the requirement. Complexity must be _earned_ by the problem, not _donated_ by the developer.

- **Recognize it:** A generic factory with configuration when a direct constructor call works. A dispatch table for two cases that could be an `if/else`.
- **Apply it:** Write the straightforward version first. Introduce indirection only when the straight path fails or when a real requirement demands it.
- **Anti-pattern: "Astronaut architecture"** — building for requirements that don't exist yet.
- **Vocabulary:** Distinguish **essential complexity** (inherent to the problem — a session lifecycle state machine) from **accidental complexity** (introduced by the solution — a metaclass-based registry to avoid typing two lines).

### YAGNI — You Aren't Gonna Need It

Do not build for hypothetical future requirements. Build what's needed now, and design so the code can be extended later — but don't extend it yet.

- **Recognize it:** Adding a plugin system when there's one implementation. Making something configurable when the value never changes. Adding an interface when there's one concrete type.
- **Apply it:** Ask: "Is there a second consumer today?" If no, don't abstract.
- **Anti-pattern: "Premature abstraction"** — extracting a base class, interface, or utility for a pattern that occurs once. The abstraction adds indirection cost with zero reuse benefit.
- **Bend it:** Known-upcoming requirements within the current work scope can justify forward design. Speculative requirements beyond the scope cannot.

### Loose Coupling

Modules interact through narrow, explicit interfaces. A change inside one module does not force changes in others.

- **Recognize it:** Many files importing a global singleton. A function that requires knowledge of an object's internal structure. A module that breaks when an unrelated module changes.
- **Apply it:** Pass dependencies through function parameters or constructor injection. Define narrow interfaces. Hide implementation details behind stable contracts.
- **Anti-pattern: "God object dependency"** — a single object (config, db, event bus) that everything imports directly, creating an invisible web of coupling.
- **Vocabulary:** **Afferent coupling** (incoming — how many modules depend on me) means the module is hard to change safely. **Efferent coupling** (outgoing — how many modules I depend on) means the module is fragile.

### High Cohesion

Everything in a module is related to its single purpose. Cohesion is SRP's twin — SRP says "one responsibility," cohesion says "keep related things together."

- **Recognize it:** A utility module with functions for string formatting, date parsing, and file I/O. A class with methods that operate on completely different data.
- **Apply it:** Group by domain concern, not by technical category. A `session_lifecycle` module that handles creation, updates, and cleanup is cohesive. A `helpers` module is not.
- **Anti-pattern: "Utility drawer"** — a module named `utils`, `helpers`, or `common` that collects unrelated functions because they didn't fit anywhere else.

### Composition over Inheritance

Build complex behavior by combining simple, independent pieces — not by extending class hierarchies.

- **Recognize it:** A deep inheritance tree where subclasses override parent behavior in surprising ways. A base class that grows to accommodate every variant.
- **Apply it:** Use mixins, protocols, and delegation. Focused mixins that each handle one concern compose cleanly.
- **Anti-pattern: "Fragile base class"** — changes to a parent class break subclasses in unexpected ways because of implicit contracts.
- **Vocabulary:** Favor "has-a" over "is-a." An adapter _has_ input handling behavior (composition), rather than _being_ an input handler (inheritance).

### Law of Demeter — Principle of Least Knowledge

Only talk to your immediate collaborators. Don't reach through objects to access their internals.

- **Recognize it:** `session.adapter_metadata.telegram.topic_id` — three dots, three coupling points. The caller must know the internal structure of Session, SessionAdapterMetadata, and TelegramAdapterMetadata.
- **Apply it:** Ask the object that owns the data: `session.get_channel_id()` or `adapter.get_topic_id(session)`. One dot.
- **Anti-pattern: "Train wreck"** — a chain of method calls or attribute accesses that couples the caller to deep internal structure.
- **Bend it:** Navigating stable, well-typed data structures (e.g., `config.telegram.bot_token`) is acceptable. The principle targets _behavioral_ chains where internals may change.

### Encapsulation

Hide internal state and expose behavior through explicit interfaces. The outside world interacts with _what_ an object does, not _how_ it stores its data.

- **Recognize it:** External code directly reading and writing internal dictionaries. A module's behavior depending on another module's private fields.
- **Apply it:** Make state private. Provide methods that express intent (`session.activate()` not `session.status = "active"`). Validate state transitions internally.
- **Anti-pattern: "Anemic domain model"** — objects that are just data bags with no behavior, where all logic lives in external functions that manipulate the data directly.

### Fail Fast

When a contract is violated, stop immediately with a clear diagnostic. Do not attempt to continue with corrupted state.

- **Recognize it:** A function receives `None` for a required parameter and silently substitutes a default. A database query returns unexpected data and the code proceeds with partial results.
- **Apply it:** Assert preconditions at function entry. Raise typed exceptions with enough context to diagnose the problem. Validate at boundaries, trust within.
- **Anti-pattern: "Defensive programming gone wrong"** — so many fallbacks and defaults that the system never crashes, but silently produces wrong results.
- **Vocabulary:** Distinguish **boundaries** (where fail-fast applies — user input, API responses, adapter outputs) from **internals** (where types and contracts guarantee correctness and defensive checks add noise).

### Immutability Preference

Default to immutable data. Mutable state is a liability — every mutation is a potential source of bugs, race conditions, and invisible coupling.

- **Recognize it:** A function that modifies its input argument. A shared dictionary that multiple coroutines read and write. A dataclass with mutable fields that gets passed around.
- **Apply it:** Use frozen dataclasses. Return new objects instead of mutating. Keep mutable state in a single owner with explicit lifecycle.
- **Anti-pattern: "Spooky action at a distance"** — code modifies a shared object and callers elsewhere observe unexpected changes without knowing why.
- **Bend it:** Performance-critical hot paths or accumulation patterns (building a response incrementally) may justify local mutability. The principle targets _shared_ mutable state, not all mutation.

## Tensions

- **DRY vs. Decoupling:** Extracting shared code can couple unrelated domains. When two domains evolve independently, duplication is healthier than a shared abstraction that becomes a change bottleneck.
- **KISS vs. DIP:** Dependency inversion adds indirection. In a monolith, apply it at major architectural boundaries, not at every function call.
- **YAGNI vs. Extensibility:** Building only for today can make tomorrow's changes harder. The resolution: write simple code that is _easy to extend_ without _already being extended_.
- **Fail Fast vs. Resilience:** Services need uptime. The resolution: fail fast at the operation level, recover at the service level. A single request fails loudly; the daemon stays up.
- **Encapsulation vs. Transparency:** Hiding internals can make debugging harder. The resolution: hide _state_, expose _diagnostics_ (logging, status methods, health checks).
