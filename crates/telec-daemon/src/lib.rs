//! Runtime shell for the long-running `telec-daemon` process.

mod runtime;

pub use runtime::{
    DaemonRuntime, OsShutdownSource, RuntimeError, ServiceLoop, ServiceLoopError, ShutdownSource,
    DEFAULT_SHUTDOWN_TIMEOUT,
};
