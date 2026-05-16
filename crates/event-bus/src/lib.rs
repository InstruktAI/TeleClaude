//! event-bus — Redis Streams + pub/sub wrapper.
//!
//! Single transport for v2 events. `emit` publishes envelopes; `subscribe`
//! returns a stream of typed events with idempotency-key dedup.

pub mod client;
pub mod envelope;
pub mod errors;

pub use client::EventBus;
pub use envelope::EventEnvelope;
pub use errors::EventBusError;
