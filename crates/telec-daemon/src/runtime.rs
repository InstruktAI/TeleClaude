use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tracing::{info, warn};

pub const DEFAULT_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{message}")]
pub struct ServiceLoopError {
    message: String,
}

impl ServiceLoopError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum RuntimeError {
    #[error("failed to install {signal} signal handler: {source}")]
    SignalHandler {
        signal: &'static str,
        #[source]
        source: std::io::Error,
    },
    #[error("service loop {name} exited before shutdown")]
    LoopExited { name: &'static str },
    #[error("service loop {name} failed: {source}")]
    LoopFailed {
        name: &'static str,
        #[source]
        source: ServiceLoopError,
    },
    #[error("service loop task {name} failed to join: {source}")]
    LoopJoinFailed {
        name: &'static str,
        #[source]
        source: tokio::task::JoinError,
    },
    #[error("service loop {name} shutdown failed: {source}")]
    LoopShutdownFailed {
        name: &'static str,
        #[source]
        source: ServiceLoopError,
    },
    #[error("shutdown timed out after {timeout:?}")]
    ShutdownTimedOut { timeout: Duration },
}

#[async_trait]
pub trait ServiceLoop: Send + Sync {
    fn name(&self) -> &'static str;

    async fn run(&self) -> Result<(), ServiceLoopError>;

    async fn shutdown(&self) -> Result<(), ServiceLoopError>;
}

#[async_trait]
pub trait ShutdownSource: Send + Sync {
    async fn wait(&self) -> Result<(), RuntimeError>;
}

pub struct OsShutdownSource;

#[async_trait]
impl ShutdownSource for OsShutdownSource {
    async fn wait(&self) -> Result<(), RuntimeError> {
        wait_for_os_shutdown_signal().await
    }
}

pub struct DaemonRuntime {
    loops: Vec<Arc<dyn ServiceLoop>>,
    shutdown_timeout: Duration,
}

impl DaemonRuntime {
    pub fn empty() -> Self {
        Self {
            loops: Vec::new(),
            shutdown_timeout: DEFAULT_SHUTDOWN_TIMEOUT,
        }
    }

    pub fn new(loops: Vec<Arc<dyn ServiceLoop>>, shutdown_timeout: Duration) -> Self {
        Self {
            loops,
            shutdown_timeout,
        }
    }

    pub fn register_loop(&mut self, service_loop: Arc<dyn ServiceLoop>) {
        self.loops.push(service_loop);
    }

    pub async fn run(&self, shutdown_source: &dyn ShutdownSource) -> Result<(), RuntimeError> {
        info!(
            service_loop_count = self.loops.len(),
            "daemon runtime starting"
        );

        let mut running = self.spawn_loops();

        tokio::select! {
            shutdown = shutdown_source.wait() => {
                shutdown?;
                info!("daemon runtime shutdown signal received");
            }
            completed = running.join_next(), if !running.is_empty() => {
                match completed {
                    Some(Ok(Ok(name))) => return Err(RuntimeError::LoopExited { name }),
                    Some(Ok(Err(error))) => return Err(error),
                    Some(Err(error)) => {
                        return Err(RuntimeError::LoopJoinFailed {
                            name: "unknown",
                            source: error,
                        });
                    }
                    None => {}
                }
            }
        }

        let shutdown_result = self.shutdown_loops().await;
        running.abort_all();
        while let Some(joined) = running.join_next().await {
            if let Err(error) = joined {
                if !error.is_cancelled() {
                    warn!(error = %error, "service loop task failed while aborting");
                }
            }
        }

        shutdown_result?;
        info!("daemon runtime stopped");
        Ok(())
    }

    fn spawn_loops(&self) -> JoinSet<Result<&'static str, RuntimeError>> {
        let mut running = JoinSet::new();
        for service_loop in &self.loops {
            let service_loop = Arc::clone(service_loop);
            let name = service_loop.name();
            running.spawn(async move {
                info!(service_loop = name, "service loop starting");
                service_loop
                    .run()
                    .await
                    .map_err(|source| RuntimeError::LoopFailed { name, source })?;
                Ok(name)
            });
        }
        running
    }

    async fn shutdown_loops(&self) -> Result<(), RuntimeError> {
        timeout(self.shutdown_timeout, async {
            for service_loop in &self.loops {
                let name = service_loop.name();
                info!(service_loop = name, "service loop shutdown starting");
                service_loop
                    .shutdown()
                    .await
                    .map_err(|source| RuntimeError::LoopShutdownFailed { name, source })?;
                info!(service_loop = name, "service loop shutdown complete");
            }
            Ok(())
        })
        .await
        .map_err(|_| RuntimeError::ShutdownTimedOut {
            timeout: self.shutdown_timeout,
        })?
    }
}

#[cfg(unix)]
async fn wait_for_os_shutdown_signal() -> Result<(), RuntimeError> {
    use tokio::signal::unix::{signal, SignalKind};

    let mut terminate =
        signal(SignalKind::terminate()).map_err(|source| RuntimeError::SignalHandler {
            signal: "SIGTERM",
            source,
        })?;

    tokio::select! {
        interrupt = tokio::signal::ctrl_c() => {
            interrupt.map_err(|source| RuntimeError::SignalHandler {
                signal: "SIGINT",
                source,
            })?;
        }
        _ = terminate.recv() => {}
    }

    Ok(())
}

#[cfg(not(unix))]
async fn wait_for_os_shutdown_signal() -> Result<(), RuntimeError> {
    tokio::signal::ctrl_c()
        .await
        .map_err(|source| RuntimeError::SignalHandler {
            signal: "SIGINT",
            source,
        })
}
