//! Reconciliation control loop.
//!
//! Owns installation desired-state convergence for the Rust daemon: channel
//! policy, exactly-once applied-version state, fleet capability checks,
//! ordered convergence, cluster events, and the inbox-driven runner.

pub mod capability_map;
pub mod convergence;
pub mod errors;
pub mod events;
pub mod ledger;
pub mod policy;
pub mod runner;

pub use capability_map::{
    CapabilityMapProvider, FleetCapabilityEntry, FleetCapabilityMap,
    RedisHeartbeatCapabilityMapProvider, StaticCapabilityMapProvider,
    FLEET_CROSS_VERSION_INTEROP_FEATURE_ID,
};
pub use convergence::{
    CommandStepExecutor, ConvergenceExecutor, ConvergenceOutcome, ConvergencePlan, ConvergenceStep,
    ConvergenceStepExecutor, MigrationGate, MigrationGateKind,
};
pub use errors::ReconciliationError;
pub use events::{
    EventBusPublisher, MemoryEventPublisher, ReconciliationEventPublisher,
    RECONCILIATION_CONVERGED, RECONCILIATION_DRIFT_DETECTED, RECONCILIATION_FAILED,
};
pub use ledger::{AppliedVersionLedger, ConvergenceRunRecord, ConvergenceRunStatus};
pub use policy::{select_target, ReleaseKind, ReleaseSignal, TargetVersion};
pub use runner::{
    ConfigServiceDesiredStateProvider, DesiredState, DesiredStateProvider, ReconciliationRunner,
    RunnerConfig, StaticDesiredStateProvider,
};
