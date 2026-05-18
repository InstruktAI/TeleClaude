---
description: 'Rust language usage rules: typing, error handling, ownership, async, traits, module structure, idioms, anti-patterns.'
id: 'software-development/policy/rust/core'
scope: 'domain'
type: 'policy'
visibility: 'public'
---

# Rust Core — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/rust/testing.md

## Rules

### Type system

1. **No `unwrap()` in production code.** Production paths return `Result` or
   `Option` and propagate via `?`. `unwrap()` is allowed in tests, examples,
   and `main()` of binary crates where the failure is intentionally fatal —
   nowhere else.
2. **No `expect("...")` as a substitute for `unwrap()`.** Same rule. If
   you genuinely need fatal failure with context, use a typed error and
   propagate; the binary's `main` decides whether to print and exit.
3. **No `panic!()` in library crates.** Libraries return errors; binaries
   panic only at startup when invariants aren't met (e.g. missing config).
   `unreachable!()` is fine for genuinely unreachable match arms with
   exhaustive enums.
4. **No `unsafe` without justification.** Every `unsafe` block requires a
   safety-comment explaining the invariants and why they hold. PRs that
   add `unsafe` without justification are rejected. Prefer safe
   abstractions from `std`, `bytes`, `parking_lot`, etc.
5. **Use enums for discriminated data, not bool flags or magic strings.**
   `enum LifecyclePhase { Intake, Drafting, Review, ... }`, not
   `phase: String` or pairs of booleans.
6. **Use `Option<T>` for "may not exist" and `Result<T, E>` for "may fail."**
   Don't conflate them. Don't use `Option` to represent error states.
7. **Use newtypes for domain identifiers.** `SessionId(Uuid)`, `Slug(String)`,
   `ProjectId(Uuid)`. Prevents passing the wrong identifier to a function
   expecting another type. Define them in `crates/shared/src/ids.rs`.
8. **Prefer `&str` over `String` in function parameters.** Accept the
   borrowed form; let callers decide whether to allocate. Return owned
   types when the function constructs them.

### Error handling

9. **Library crates use `thiserror` for typed errors.** Each error variant is
   explicit; consumers can pattern-match. Errors carry context relevant to
   the consumer.

   ```rust
   #[derive(Debug, thiserror::Error)]
   pub enum WorkflowError {
       #[error("todo not found: {0}")]
       NotFound(Slug),
       #[error("invalid lifecycle transition: {from:?} → {to:?}")]
       InvalidTransition { from: LifecyclePhase, to: LifecyclePhase },
       #[error(transparent)]
       Db(#[from] sqlx::Error),
   }
   ```

10. **Binary crates may use `anyhow` for top-level error context.** Inside
    `main()` and command handlers where typed errors aren't needed, `anyhow`
    keeps error propagation ergonomic. Service code in libraries does not
    use `anyhow` in public signatures.
11. **Always include context when wrapping errors.** Use
    `.context("description")` or `.map_err(|e| WorkflowError::...)`. A
    bare `?` that loses context makes debugging painful.
12. **Never swallow errors silently.** No `let _ = result;` to discard a
    `Result`. If you genuinely don't care, log at debug or higher and
    explain why.

### Ownership and borrowing

13. **Default to borrowing.** Take `&T` parameters; return owned `T` when
    the function constructs the value, otherwise return `&T` tied to the
    input's lifetime.
14. **Use `Arc<T>` only for shared ownership across tasks/threads.** Not as
    a default. `Box<T>` for heap allocation without sharing; `Arc<T>` only
    when multiple owners genuinely need the value concurrently.
15. **Use `Rc<T>` rarely in TeleClaude.** Async code is the norm and
    `tokio::task::spawn` requires `Send`. `Arc<T>` is almost always the
    right choice in async contexts.
16. **Avoid `.clone()` as a "make the borrow checker happy" tool.** Each
    `.clone()` should answer "why is owning a second copy correct here?"
    Cheap clones (`Arc::clone`, small types) are fine; deep clones of large
    structs need justification.

### Async

17. **Use Tokio as the async runtime.** Workspace pins `tokio` with
    `["full"]` features. No alternative runtimes (`async-std`, `smol`)
    without explicit justification.
18. **`async fn` returns `impl Future`.** No manual `Future` implementations
    unless writing infrastructure-level code (rare).
19. **Use `tokio::spawn` for fire-and-forget tasks.** Use `tokio::join!`
    or `tokio::try_join!` for awaiting multiple tasks concurrently.
20. **Don't block in async functions.** No `std::thread::sleep`, no
    blocking I/O, no CPU-heavy synchronous work without `tokio::task::spawn_blocking`.
21. **Use `async_trait` for trait methods that need to be async.** Until
    native async traits stabilize for object-safe trait objects, the
    `async_trait` crate is the standard.
22. **`#[tokio::main]` only on `main()` of binary crates.** Library code
    never uses it; library code is `async fn` and the runtime is provided
    by the caller.

### Traits

23. **Add a trait only when you need a test double or you have two real
    implementations.** Don't pre-abstract. See `rust/testing.md` for the
    detailed rule.
24. **Prefer `Arc<dyn Trait>` for swappable I/O.** Generics
    (`<T: Trait>`) only when (a) benchmarks show dyn is too slow, or (b)
    the type is part of a compile-time contract you want enforced.
25. **Traits should be small and focused.** A trait with 12 methods is
    rarely the right abstraction. Decompose into multiple traits or
    reconsider whether the abstraction is correct.
26. **Mark trait objects as `Send + Sync` when they must cross task
    boundaries.** Most service dependencies (`EventBus`, `IdentityResolver`)
    need this; the bound goes on the trait definition.

### Module structure

27. **`lib.rs` is the public surface.** It re-exports public types and
    functions; it does not contain implementation. Implementation lives in
    submodules.
28. **Internal modules use leading underscore.** `mod _state;`,
    `mod _internal;`. Signals "not part of the public crate surface."
29. **Public modules use no underscore.** `pub mod models;`,
    `pub mod events;`. Part of the crate's public API.
30. **No `mod.rs` files.** Use `<name>.rs` at the parent level for the
    module file; `<name>/<submodule>.rs` for nested. Modern Rust convention
    (Rust 2018+); avoids the historical `mod.rs` pattern.
31. **No star imports.** `use crate::foo::*;` is forbidden. Explicit imports
    or grouped imports (`use crate::foo::{a, b, c};`).
32. **Keep imports at the top of the file.** Grouped: std → external crates
    → internal crates → current crate. `cargo fmt` enforces ordering within
    groups.

### Naming

33. **Crate names: snake_case.** `agent_runtime`, `event_bus`, `workflow`.
34. **Binary names: kebab-case.** `telec`, `telec-tui`, `telec-daemon`.
35. **Types: PascalCase.** `Todo`, `Principal`, `EventEnvelope`.
36. **Functions and methods: snake_case.** `list_todos`, `resolve_caller`.
37. **Constants: SCREAMING_SNAKE_CASE.** `const MAX_RETRIES: u32 = 3;`.
38. **Lifetimes: short, lowercase, meaningful.** `'a`, `'src`, `'tx`. Don't
    invent verbose names; lifetimes are scoped enough that short names work.

### Style and tooling

39. **`cargo fmt` runs on pre-commit.** Never commit unformatted code.
40. **`cargo clippy --all-targets -- -D warnings` runs on pre-commit.** Clippy
    warnings are errors. Silence individual lints with `#[allow(...)]` and
    a comment explaining why.
41. **Workspace dependencies declared once.** Shared deps go in
    `[workspace.dependencies]` at the root `Cargo.toml`. Member crates
    reference them with `workspace = true`.
42. **Pin major versions in dependencies.** `tokio = "1"` is fine;
    `tokio = "*"` is not. `Cargo.lock` is committed for binary crates,
    not for library crates intended for external use.
43. **No `dbg!()` or `println!()` in production code.** Use `tracing`
    macros for logging. `dbg!()` is allowed in development; pre-commit
    hook rejects it from committed code.
44. **No `TODO`/`FIXME` comments without an issue link.** If something
    must be deferred, write a real todo (`telec todo dump`) and reference
    the slug. Drive-by `// TODO: fix this later` comments accrete.

### Anti-patterns to refuse

45. **No `lazy_static` or `OnceCell` for service singletons.** Services use
    constructor injection. Globals defeat testability and obscure wiring.
46. **No `Mutex<HashMap>` for shared state that should live in
    Postgres/Redis.** If state needs to survive a process restart, it's
    in Postgres. If it needs cross-process visibility, it's in Redis. In-
    process shared state is rare and needs justification.
47. **No mixed `async` and blocking in one stack.** If a function is async,
    everything down its call tree is async. Bridging requires explicit
    `spawn_blocking` and is the exception, not the rule.
48. **No `Box<dyn Error>` in library public APIs.** Use typed errors via
    `thiserror`. `Box<dyn Error>` is acceptable internally as a catch-all
    but never in a public signature.
49. **No `impl Trait` in return position for library public APIs that need
    to be nameable.** If callers need to name the type (e.g., store it),
    use a typed return.
50. **No mutating arguments through `&mut` where ownership transfer is
    cleaner.** Take ownership and return the modified value when it
    expresses intent better.

## Rationale

Rust's compiler is the discipline mechanism. The rules above lean into that —
typed errors, no `unwrap`, no `unsafe`, explicit ownership, explicit traits.
Each rule has a failure mode it prevents that Rust's type system makes
catchable at compile time when the rule is followed.

The "no globals" stance reflects the v2 architecture's services-as-crates
model: every binary wires its dependencies explicitly. Globals defeat that
model and reintroduce hidden coupling.

The `dyn` vs generics default (use `dyn`) reflects the actual workload (I/O
bound, not CPU bound) — dynamic dispatch cost is negligible compared to the
I/O it wraps, and `dyn` is simpler.

## Scope

Applies to all Rust code in this repository: service crates, binary crates,
infrastructure crates, test code, build scripts.

## Enforcement

- `cargo fmt --check` runs on pre-commit; commits with formatting violations
  are rejected.
- `cargo clippy --all-targets -- -D warnings` runs on pre-commit; clippy
  warnings block commit.
- `cargo test --workspace` runs on pre-commit.
- PRs that introduce `unwrap()`, `expect()`, `panic!()`, or `unsafe` in
  production code without justification are rejected at review.
- PRs that introduce `lazy_static`/`OnceCell` for services, or `mod.rs`
  files, are rejected at review.
- Suppressed clippy lints (`#[allow(...)]`) require a comment explaining
  why.

## Exceptions

- `main()` of binary crates may `unwrap()` or `expect()` at startup when
  invariants must hold or the process can't usefully run.
- Tests, examples, and benchmarks may use `unwrap()`/`expect()` freely.
- `unsafe` is allowed when wrapping FFI or when implementing a fundamental
  abstraction that requires it; every block requires a safety comment.
- The "two real implementations or test double" rule for traits has a
  carve-out for marker traits (`Send`, `Sync`, etc.) and for stdlib trait
  implementations.
