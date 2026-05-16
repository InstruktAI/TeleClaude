//! Library facade for `telec-cli`.
//!
//! The binary is the primary surface; this lib exists so integration tests
//! under `tests/` can call into individual subcommand modules without
//! shelling out to the compiled binary. Modules are re-included via
//! `#[path]` so the source of truth stays in the `src/<module>.rs` files
//! the binary consumes. Each compilation target (bin + lib) gets its own
//! instantiation of these modules; they share no static state.

/// `migrate-workflow-v1` subcommand body — owned by Wave G1.
#[path = "migrate.rs"]
pub mod migrate;
