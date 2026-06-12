use std::collections::BTreeSet;
use std::future::Future;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use event_bus::EventEnvelope;
use integration::{NormalizedEvent, ProviderRegistry, VerifiedEventRelay};
use telec_daemon::{IngressServiceLoop, ServiceLoop};
use tokio::time::timeout;

struct UnusedRelay;

impl VerifiedEventRelay for UnusedRelay {
    fn relay<'a>(
        &'a self,
        _event: NormalizedEvent,
    ) -> Pin<
        Box<dyn Future<Output = Result<EventEnvelope, integration::IntegrationError>> + Send + 'a>,
    > {
        Box::pin(async { panic!("shutdown test does not relay events") })
    }
}

#[tokio::test]
async fn ingress_loop_shutdown_completes_bounded_server_run() {
    let server = integration::IngressServer::with_relay(
        SocketAddr::from((Ipv4Addr::LOCALHOST, 0)),
        BTreeSet::from([IpAddr::V4(Ipv4Addr::LOCALHOST)]),
        ProviderRegistry::with_github("test-secret"),
        Arc::new(UnusedRelay),
    )
    .expect("ingress server builds");
    let service_loop = Arc::new(IngressServiceLoop::new(server));

    let runner = {
        let service_loop = Arc::clone(&service_loop);
        tokio::spawn(async move { service_loop.run().await })
    };
    tokio::time::sleep(Duration::from_millis(50)).await;

    service_loop.shutdown().await.expect("shutdown signals");
    timeout(Duration::from_secs(2), runner)
        .await
        .expect("run completes within bounded timeout")
        .expect("run task joins")
        .expect("loop exits cleanly");
}
