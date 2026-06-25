---
description: 'Rust testing patterns: DI via constructor injection, test colocation, sqlx::test for DB, builders for test data, hand-written doubles by default.'
visibility: 'public'
---

# Rust Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md

## Rules

### Spec-binding and the unit-test exception

- **Rust keeps colocated unit tests** — the documented exception to the generic no-agent-unit-test
  rule. The compiler, type system, and ownership enforce the unit-level correctness that dynamic
  languages chase with tests, and `#[cfg(test)] mod tests` over pure functions is idiomatic and
  cheap. These colocated units are not spec-bound.
- **Spec-bound behavior lives in integration tests** at `crates/<crate>/tests/<slug>.rs`, mirroring
  the feature spec `docs/project/spec/feature/<domain>/<slug>.md` (the domain resolves to a crate).
  Each test binds its scenario with a `// spec: <spec_id> <UC-id>` comment naming the scenario it
  realizes; Rust bindings are checked at review. Functional, smoke, and integration levels follow
  the generic policy.

### Dependency injection — the wiring model

1. **Constructor injection only.** Services take their dependencies in `new()`. No globals. No `lazy_static`. No `OnceCell` singletons for services.

   ```rust
   pub struct WorkflowService {
       pool: PgPool,
       event_bus: Arc<dyn EventBus>,
   }

   impl WorkflowService {
       pub fn new(pool: PgPool, event_bus: Arc<dyn EventBus>) -> Self {
           Self { pool, event_bus }
       }
   }
   ```

2. **Each binary wires its dependencies explicitly in `main`.** No central `Container` struct is required by default. A Container is a refactor target only when two or more binaries share identical wiring for ≥5 services. Until then, explicit `main` wiring is simpler:

   ```rust
   fn main() -> Result<()> {
       observability::init("telec");
       let config = config::load()?;
       let pool = storage::pool_for_service("workflow", &config).await?;
       let event_bus: Arc<dyn EventBus> = Arc::new(RedisEventBus::new(&config));
       let workflow = WorkflowService::new(pool, event_bus.clone());
       cli::dispatch(&workflow).await
   }
   ```

3. **Tests construct services directly.** No production Container in tests. Tests build only the dependencies the test needs:

   ```rust
   #[sqlx::test]
   async fn list_todos_returns_inserted(pool: PgPool) {
       let event_bus: Arc<dyn EventBus> = Arc::new(MockEventBus::default());
       let svc = WorkflowService::new(pool, event_bus);
       // ... exercise svc ...
   }
   ```

### Trait abstraction — when and when not

4. **Introduce a trait only when one of these is true:**
   - You need a test double AND the production code does I/O that's expensive or impossible to set up in unit tests.
   - You have two real implementations now (not "might have someday").

5. **Otherwise pass concrete types.** `PgPool` is concrete. `Config` is concrete. `Pool<Postgres>` is concrete. Reach for a trait only when test doubles or polymorphism are concrete needs.

6. **`Arc<dyn Trait>` by default for swappable I/O.** Generics (`<T: Trait>`) only when (a) benchmarks show dynamic dispatch is hurting a hot path, or (b) compile-time type enforcement is the point.

### Pure-function preference

7. **Extract logic to pure functions before reaching for DI.** The best testable code has no dependencies because it has no I/O:

   ```rust
   // In _state.rs — pure function, trivially testable
   pub fn next_lifecycle_phase(current: LifecyclePhase, signal: Signal) -> LifecyclePhase {
       match (current, signal) { /* ... */ }
   }

   // In service.rs — I/O wrapper around the pure logic
   pub async fn advance_todo(&self, slug: &Slug, signal: Signal) -> Result<Todo> {
       let todo = self.read(slug).await?;
       let next = next_lifecycle_phase(todo.phase, signal);  // pure
       self.persist(slug, next).await?;                       // I/O
       self.event_bus.emit(/* ... */).await?;                 // I/O
       Ok(/* ... */)
   }
   ```

   Unit-test `next_lifecycle_phase` directly with no mocks. The I/O wrapper has fewer paths to test and they're behavioral.

8. **Most logic should live in pure functions.** DI is for I/O glue. If a service struct has many methods that don't touch `self.pool` or `self.event_bus`, those should be standalone functions in the same module.

### Test location

9. **Unit tests colocated with code.** `#[cfg(test)] mod tests` at the bottom of each source file:

   ```rust
   pub fn next_lifecycle_phase(current: LifecyclePhase, signal: Signal) -> LifecyclePhase {
       /* ... */
   }

   #[cfg(test)]
   mod tests {
       use super::*;

       #[test]
       fn intake_advances_to_drafting_on_input_received() {
           let next = next_lifecycle_phase(LifecyclePhase::Intake, Signal::InputReceived);
           assert_eq!(next, LifecyclePhase::Drafting);
       }
   }
   ```

10. **Integration tests in `crates/<service>/tests/`** — separate compilation unit, exercises the crate's public API:

    ```
    crates/workflow/
    ├── src/
    │   ├── lib.rs
    │   ├── _state.rs       (with colocated unit tests)
    │   └── service.rs      (with colocated unit tests)
    └── tests/
        ├── common/         (test helpers, builders)
        │   └── mod.rs
        └── workflow_api.rs (integration tests against public API)
    ```

11. **E2E tests sparingly, in a dedicated `tests/e2e/` crate.** Critical paths only. Real Postgres + Redis via docker-compose. Slow; not run in pre-commit hooks.

### Database testing

12. **Use `sqlx::test` for all DB-touching tests.** It provides transaction-per-test with automatic rollback. No testcontainers spin-up per test:

    ```rust
    #[sqlx::test(migrations = "../workflow/migrations")]
    async fn create_todo_persists(pool: PgPool) {
        let svc = WorkflowService::new(pool.clone(), mock_bus());
        svc.create_todo(&ctx(), a_todo().build()).await.unwrap();
        let todos = sqlx::query_as!(TodoRow, "SELECT * FROM workflow.todos").fetch_all(&pool).await.unwrap();
        assert_eq!(todos.len(), 1);
    }
    ```

13. **`DATABASE_URL` must be set for tests to run.** CI provides Postgres as a service. Local dev brings up Postgres via `docker-compose`. Tests that require DB without `DATABASE_URL` set must fail loudly, not silently skip.

### Test data — builders, not fixtures

14. **Use the builder pattern for test data construction.** Sensible defaults, fluent overrides:

    ```rust
    // tests/common/mod.rs
    #[derive(Default)]
    pub struct TodoBuilder {
        slug: Option<String>,
        phase: Option<LifecyclePhase>,
    }

    impl TodoBuilder {
        pub fn with_slug(mut self, slug: &str) -> Self {
            self.slug = Some(slug.into());
            self
        }
        pub fn with_phase(mut self, phase: LifecyclePhase) -> Self {
            self.phase = Some(phase);
            self
        }
        pub fn build(self) -> Todo {
            Todo {
                slug: self.slug.unwrap_or_else(|| "test-todo".into()),
                phase: self.phase.unwrap_or(LifecyclePhase::Intake),
                /* sensible defaults for everything else */
            }
        }
    }

    pub fn a_todo() -> TodoBuilder { TodoBuilder::default() }
    ```

    Use:

    ```rust
    let todo = a_todo().with_slug("my-todo").with_phase(LifecyclePhase::Drafting).build();
    ```

15. **No fixture files (`.json`, `.yaml`) unless the data shape is fundamentally not-Rust** (e.g., HTTP request/response samples for contract tests). Builders compose better, refactor cleanly, and don't drift from the type system.

### Mocking — hand-write by default

16. **Hand-write test doubles for simple, heavily-used traits.** A trait with 2-3 methods used in many tests is clearer as a hand-written struct:

    ```rust
    // tests/common/mod.rs
    #[derive(Default)]
    pub struct MockEventBus {
        pub emitted: Mutex<Vec<EventEnvelope>>,
    }

    #[async_trait]
    impl EventBus for MockEventBus {
        async fn emit(&self, event: EventEnvelope) -> Result<()> {
            self.emitted.lock().await.push(event);
            Ok(())
        }
        async fn subscribe(&self, _channel: &str) -> Result<Subscription> {
            unimplemented!("not used in this test")
        }
    }
    ```

17. **Use `mockall` for complex traits where signature drift is a real cost.** Trait with 8+ methods, used in expectation-heavy tests, signature changes regularly: `mockall` keeps mocks in sync automatically. Decide per-trait, not globally.

18. **Never mock what you don't have to.** If a function is pure, don't mock its caller's dependencies — call the pure function directly. The more mocks a test contains, the less it tests behavior.

### Behavior over implementation

19. **Tests call public functions and assert on observable outputs.** Tests do not poke at internal state. Tests do not call `pub(crate)` helpers "for visibility." Tests do not assert on field values that aren't part of the contract.

20. **Don't widen visibility for testing.** If you need to test something that's private, either:
    - Extract it to a pure function that's its own public API at module scope, OR
    - Test it through the public API that uses it.

    Making something `pub(crate) fn _internal_helper()` for tests is the failure mode that binds tests to internals.

21. **Do not test native shape or wiring for coverage.** Rust struct fields,
    enum variants, builder defaults, trait-object wiring, and DI/container
    registration are not test targets by themselves. Assert accepted/rejected
    external input, public API output, persisted/wire behavior, or the runtime
    behavior the wiring enables.

22. **Test names describe behavior, not implementation.** `intake_advances_to_drafting_on_input_received`, not `test_match_returns_drafting`.

### Async testing

23. **Use `#[tokio::test]` for async tests.** Single-threaded runtime by default — deterministic, fast.

24. **Use `#[tokio::test(flavor = "multi_thread")]` for concurrency tests.** Required when testing actual concurrent behavior; not the default.

### Snapshot testing

25. **Use `insta` deliberately, not as a default.** Snapshot tests are appropriate when:
    - The output is stable and any change requires explicit review (CLI text output, formatted error messages, generated JSON contracts).
    - The output shape is too large to assert inline meaningfully.

26. **Snapshot tests are not a substitute for behavior assertions.** A snapshot says "the output looks like this." A behavior assertion says "the right thing happened." Prefer behavior assertions when the right output is small.

27. **Review snapshot diffs as code.** Auto-accepting `cargo insta accept` without inspection is the snapshot-rubber-stamping anti-pattern.

### Property-based testing

28. **Use `proptest` where invariants are the contract.** Parsers, validators, state machines, serialization round-trips — these have invariants (`parse(format(x)) == x`, `serialize(deserialize(s)) == s`) that benefit from property tests.

29. **Don't add property tests where example tests suffice.** Most service code is behavioral; example tests are clearer. Property tests earn their complexity when the input space is genuinely large.

### Coverage

30. **`cargo-llvm-cov` as a discovery tool.** Use it to find untested branches in critical code. Do not make coverage a quality gate (% threshold). Coverage measures lines exercised, not behavior verified.

### Test isolation

31. **No shared mutable state between tests.** Each test gets its own pool (`sqlx::test` provides this), its own mock bus, its own builders.

32. **No `#[ignore]` accumulation.** A test that's `#[ignore]`d for "flakiness" gets fixed or deleted. The standard build runs all tests.

33. **No test ordering assumptions.** Tests must pass in any order, including parallel.

## Rationale

The compiler is the discipline mechanism Python lacked. Rust testing patterns
should lean into this — types verify wiring at compile time, the borrow checker
prevents whole classes of bugs, and `sqlx::test`'s transaction rollback makes
DB tests fast enough to be the default.

The patterns above prioritize: behavior over implementation, pure functions
over mocked I/O, hand-written clarity over framework magic, explicit wiring
over runtime containers. Each is chosen to match how Rust actually works
rather than porting patterns from other languages.

The "no Container until earned" stance reflects YAGNI applied to architecture:
a Container becomes useful when multiple binaries share wiring; until they do,
the indirection costs more than it saves. Same principle for traits: add the
abstraction when the second implementation or the test double justifies it.

## Scope

Applies to all Rust code in this repository, including service crates, binary
crates, infrastructure crates, and test code.

## Enforcement

- `cargo test` and `cargo clippy` run on pre-commit and must pass; flags and scope are owned by the harness.
- New service crates without colocated unit tests are rejected at review.
- New service crates without integration tests in `tests/` are rejected at
  review.
- PRs that introduce `lazy_static`/`OnceCell` for services, or that widen
  visibility to `pub(crate)` for testing, are rejected at review.
- PRs that introduce a Container struct without justifying the wiring
  duplication threshold (≥2 binaries × ≥5 shared services) are rejected at
  review.

## Exceptions

- E2E tests may use real infrastructure (`docker-compose`-managed Postgres,
  Redis) instead of `sqlx::test`. This trades isolation for fidelity at the
  e2e level. Limited to the `tests/e2e/` crate.
- Coverage thresholds may be enforced per-crate if a service genuinely needs
  high coverage (security-sensitive code). Not a default.
