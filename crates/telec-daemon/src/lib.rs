//! Runtime shell for the long-running `telec-daemon` process.

mod ingress_loop;
mod reconciliation_loop;
mod runtime;

pub use ingress_loop::IngressServiceLoop;
pub use reconciliation_loop::ReconciliationServiceLoop;
pub use runtime::{
    DaemonRuntime, OsShutdownSource, RuntimeError, ServiceLoop, ServiceLoopError, ShutdownSource,
    DEFAULT_SHUTDOWN_TIMEOUT,
};
