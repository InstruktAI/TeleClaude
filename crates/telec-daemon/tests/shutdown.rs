use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use telec_daemon::{DaemonRuntime, RuntimeError, ServiceLoop, ServiceLoopError, ShutdownSource};
use tokio::sync::{oneshot, Mutex};
use tokio::time::timeout;

struct TestShutdownSource {
    receiver: Mutex<Option<oneshot::Receiver<()>>>,
}

impl TestShutdownSource {
    fn new(receiver: oneshot::Receiver<()>) -> Self {
        Self {
            receiver: Mutex::new(Some(receiver)),
        }
    }
}

#[async_trait]
impl ShutdownSource for TestShutdownSource {
    async fn wait(&self) -> Result<(), RuntimeError> {
        let receiver = self
            .receiver
            .lock()
            .await
            .take()
            .expect("test shutdown source is only consumed once");
        receiver
            .await
            .expect("test shutdown signal sender is alive");
        Ok(())
    }
}

struct RecordingLoop {
    shutdown_calls: Arc<AtomicUsize>,
}

impl RecordingLoop {
    fn new(shutdown_calls: Arc<AtomicUsize>) -> Self {
        Self { shutdown_calls }
    }
}

#[async_trait]
impl ServiceLoop for RecordingLoop {
    fn name(&self) -> &'static str {
        "recording-loop"
    }

    async fn run(&self) -> Result<(), ServiceLoopError> {
        std::future::pending::<()>().await;
        Ok(())
    }

    async fn shutdown(&self) -> Result<(), ServiceLoopError> {
        self.shutdown_calls.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

#[tokio::test]
async fn runtime_shutdown_drains_registered_loop_once() {
    let shutdown_calls = Arc::new(AtomicUsize::new(0));
    let mut runtime = DaemonRuntime::empty();
    runtime.register_loop(Arc::new(RecordingLoop::new(Arc::clone(&shutdown_calls))));

    let (sender, receiver) = oneshot::channel();
    let shutdown_source = TestShutdownSource::new(receiver);
    sender.send(()).expect("send test shutdown signal");

    timeout(Duration::from_millis(500), runtime.run(&shutdown_source))
        .await
        .expect("runtime returns within bounded test window")
        .expect("runtime shutdown succeeds");

    assert_eq!(shutdown_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn empty_runtime_shuts_down_cleanly_on_signal() {
    let runtime = DaemonRuntime::empty();

    let (sender, receiver) = oneshot::channel();
    let shutdown_source = TestShutdownSource::new(receiver);
    sender.send(()).expect("send test shutdown signal");

    timeout(Duration::from_millis(500), runtime.run(&shutdown_source))
        .await
        .expect("runtime returns within bounded test window")
        .expect("empty runtime shutdown succeeds");
}
