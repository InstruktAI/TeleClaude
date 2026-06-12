//! Axum webhook ingress server.

use std::collections::BTreeSet;
use std::future::Future;
use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;

use axum::body::{Body, Bytes};
use axum::extract::{ConnectInfo, Path, State};
use axum::http::{HeaderMap, Request, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::Router;
use config::models::IngressConfig;
use event_bus::EventBus;
use tokio::net::TcpListener;
use tracing::{error, info, warn};

use crate::errors::IntegrationError;
use crate::provider::{ProviderRegistry, ProviderRequest};
use crate::relay::{EventBusRelay, VerifiedEventRelay};

/// HTTP ingress server primitive owned by the integration crate.
#[derive(Clone)]
pub struct IngressServer {
    bind: SocketAddr,
    state: IngressState,
}

impl IngressServer {
    /// Build an ingress server from typed config and an event bus.
    pub fn from_config(
        config: &IngressConfig,
        event_bus: Arc<EventBus>,
    ) -> Result<Self, IntegrationError> {
        let bind = config
            .bind
            .as_deref()
            .ok_or(IntegrationError::MissingBindAddress)?;
        let bind = parse_bind_address(bind)?;
        validate_bind_address(bind)?;
        Self::new(
            bind,
            config.allowed_source.clone(),
            ProviderRegistry::from_config(config),
            event_bus,
        )
    }

    /// Build an ingress server from explicit dependencies.
    pub fn new(
        bind: SocketAddr,
        allowed_sources: BTreeSet<IpAddr>,
        providers: ProviderRegistry,
        event_bus: Arc<EventBus>,
    ) -> Result<Self, IntegrationError> {
        Self::with_relay(
            bind,
            allowed_sources,
            providers,
            Arc::new(EventBusRelay::new(event_bus)),
        )
    }

    /// Build an ingress server with an explicit relay target.
    pub fn with_relay(
        bind: SocketAddr,
        allowed_sources: BTreeSet<IpAddr>,
        providers: ProviderRegistry,
        relay: Arc<dyn VerifiedEventRelay>,
    ) -> Result<Self, IntegrationError> {
        if allowed_sources.is_empty() {
            return Err(IntegrationError::MissingAllowedSource);
        }
        Ok(Self {
            bind,
            state: IngressState {
                allowed_sources: Arc::new(allowed_sources),
                providers,
                relay,
            },
        })
    }

    /// Address the HTTP server binds to.
    pub fn bind_addr(&self) -> SocketAddr {
        self.bind
    }

    /// Build the axum application.
    pub fn router(&self) -> Router {
        self.router_with_state(self.state.clone())
    }

    fn router_with_state(&self, state: IngressState) -> Router {
        Router::new()
            .route("/webhooks/:provider", post(handle_webhook))
            .route_layer(middleware::from_fn_with_state(
                state.clone(),
                restrict_source,
            ))
            .with_state(state)
    }

    /// Bind and serve until the supplied shutdown future resolves.
    pub async fn serve<S>(&self, shutdown: S) -> Result<(), IntegrationError>
    where
        S: Future<Output = ()> + Send + 'static,
    {
        self.bind().await?.serve(shutdown).await
    }

    /// Bind the configured listener without starting the server.
    pub async fn bind(&self) -> Result<IngressListener, IntegrationError> {
        let listener = TcpListener::bind(self.bind).await?;
        Ok(IngressListener {
            listener,
            router: self.router_with_state(self.state.clone()),
        })
    }
}

/// Bound ingress listener ready to serve HTTP requests.
pub struct IngressListener {
    listener: TcpListener,
    router: Router,
}

impl IngressListener {
    /// Address selected by the OS for this listener.
    pub fn local_addr(&self) -> Result<SocketAddr, IntegrationError> {
        Ok(self.listener.local_addr()?)
    }

    /// Serve requests until the supplied shutdown future resolves.
    pub async fn serve<S>(self, shutdown: S) -> Result<(), IntegrationError>
    where
        S: Future<Output = ()> + Send + 'static,
    {
        axum::serve(
            self.listener,
            self.router
                .into_make_service_with_connect_info::<SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown)
        .await?;
        Ok(())
    }
}

#[derive(Clone)]
struct IngressState {
    allowed_sources: Arc<BTreeSet<IpAddr>>,
    providers: ProviderRegistry,
    relay: Arc<dyn VerifiedEventRelay>,
}

async fn restrict_source(
    State(state): State<IngressState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    let delivery_id = delivery_id_from_headers(request.headers());
    let Some(ConnectInfo(peer)) = request.extensions().get::<ConnectInfo<SocketAddr>>() else {
        warn!(
            delivery_id = delivery_id.as_deref().unwrap_or("unknown"),
            "ingress source refused"
        );
        return generic_rejection();
    };

    if !state.allowed_sources.contains(&peer.ip()) {
        warn!(
            delivery_id = delivery_id.as_deref().unwrap_or("unknown"),
            peer = %peer,
            "ingress source refused"
        );
        return generic_rejection();
    }

    next.run(request).await
}

async fn handle_webhook(
    Path(provider_name): Path<String>,
    State(state): State<IngressState>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let delivery_id = delivery_id_from_headers(&headers);
    let Some(provider) = state.providers.resolve(&provider_name) else {
        warn!(
            provider = %provider_name,
            delivery_id = delivery_id.as_deref().unwrap_or("unknown"),
            "ingress webhook rejected"
        );
        return generic_rejection();
    };

    let request = ProviderRequest {
        headers: &headers,
        body: body.as_ref(),
    };
    let event = match provider.verify_and_normalize(&request) {
        Ok(event) => event,
        Err(error) => {
            warn!(
                provider = %provider_name,
                delivery_id = delivery_id.as_deref().unwrap_or("unknown"),
                error = %error,
                "ingress webhook rejected"
            );
            return generic_rejection();
        }
    };

    let event_name = event.event_name.clone();
    let delivery_id = event.delivery_id.clone();
    match state.relay.relay(event).await {
        Ok(_) => {
            info!(
                provider = %provider_name,
                delivery_id = %delivery_id,
                event_name = %event_name,
                "ingress webhook accepted"
            );
            StatusCode::ACCEPTED.into_response()
        }
        Err(error) => {
            error!(
                provider = %provider_name,
                delivery_id = %delivery_id,
                event_name = %event_name,
                error = %error,
                "ingress relay failed"
            );
            StatusCode::INTERNAL_SERVER_ERROR.into_response()
        }
    }
}

fn generic_rejection() -> Response {
    StatusCode::FORBIDDEN.into_response()
}

fn delivery_id_from_headers(headers: &HeaderMap) -> Option<String> {
    headers
        .get("x-github-delivery")
        .and_then(|value| value.to_str().ok())
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn parse_bind_address(value: &str) -> Result<SocketAddr, IntegrationError> {
    value
        .parse()
        .map_err(|_| IntegrationError::InvalidBindAddress(value.to_string()))
}

fn validate_bind_address(bind: SocketAddr) -> Result<(), IntegrationError> {
    if bind.ip().is_loopback() || bind.ip().is_unspecified() {
        return Err(IntegrationError::InvalidBindAddress(bind.to_string()));
    }
    Ok(())
}
