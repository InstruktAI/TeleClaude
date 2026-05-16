//! workflow — todo + roadmap + artifacts service.
//!
//! Owns the `workflow` Postgres schema. Public surface: domain models,
//! event schemas, the lifecycle state machine, and (in Wave E1) the
//! `WorkflowService` struct.

pub mod errors;
pub mod events;
pub mod models;
pub mod service;
pub mod state_machine;

pub use service::{EventSink, TodoPatch, WorkflowService};
