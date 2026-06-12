use std::sync::Arc;

use async_trait::async_trait;
use reconciliation::ReconciliationRunner;
use tokio::sync::watch;

use crate::runtime::{ServiceLoop, ServiceLoopError};

const RECONCILIATION_LOOP_NAME: &str = "reconciliation";

pub struct ReconciliationServiceLoop {
    runner: Arc<ReconciliationRunner>,
    shutdown_tx: watch::Sender<bool>,
}

impl ReconciliationServiceLoop {
    pub fn new(runner: Arc<ReconciliationRunner>) -> Self {
        let (shutdown_tx, _) = watch::channel(false);
        Self {
            runner,
            shutdown_tx,
        }
    }
}

#[async_trait]
impl ServiceLoop for ReconciliationServiceLoop {
    fn name(&self) -> &'static str {
        RECONCILIATION_LOOP_NAME
    }

    async fn run(&self) -> Result<(), ServiceLoopError> {
        let mut shutdown_rx = self.shutdown_tx.subscribe();
        let shutdown = Box::pin(async move {
            if *shutdown_rx.borrow() {
                return;
            }
            while shutdown_rx.changed().await.is_ok() {
                if *shutdown_rx.borrow() {
                    break;
                }
            }
        });
        self.runner
            .run_until_shutdown(shutdown)
            .await
            .map_err(|error| ServiceLoopError::new(error.to_string()))
    }

    async fn shutdown(&self) -> Result<(), ServiceLoopError> {
        self.shutdown_tx.send_replace(true);
        Ok(())
    }
}
