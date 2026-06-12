use async_trait::async_trait;
use integration::IngressServer;
use tokio::sync::watch;

use crate::runtime::{ServiceLoop, ServiceLoopError};

const INGRESS_LOOP_NAME: &str = "integration-ingress";

pub struct IngressServiceLoop {
    server: IngressServer,
    shutdown_tx: watch::Sender<bool>,
}

impl IngressServiceLoop {
    pub fn new(server: IngressServer) -> Self {
        let (shutdown_tx, _) = watch::channel(false);
        Self {
            server,
            shutdown_tx,
        }
    }
}

#[async_trait]
impl ServiceLoop for IngressServiceLoop {
    fn name(&self) -> &'static str {
        INGRESS_LOOP_NAME
    }

    async fn run(&self) -> Result<(), ServiceLoopError> {
        let mut shutdown_rx = self.shutdown_tx.subscribe();
        self.server
            .serve(async move {
                if *shutdown_rx.borrow() {
                    return;
                }
                while shutdown_rx.changed().await.is_ok() {
                    if *shutdown_rx.borrow() {
                        break;
                    }
                }
            })
            .await
            .map_err(|error| ServiceLoopError::new(error.to_string()))
    }

    async fn shutdown(&self) -> Result<(), ServiceLoopError> {
        self.shutdown_tx.send_replace(true);
        Ok(())
    }
}
