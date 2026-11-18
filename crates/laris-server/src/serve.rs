//! The accept loop: connection limit, header timeout, request scope and access log around the router.

use crate::app::{AppState, Deferred, router};
use crate::log::{LogSink, RequestScope};
use axum::body::Body;
use axum::http::{HeaderValue, Request, Response};
use hyper::body::Incoming;
use hyper::service::Service;
use hyper_util::rt::{TokioIo, TokioTimer};
use hyper_util::service::TowerToHyperService;
use std::convert::Infallible;
use std::future::Future;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::net::TcpListener;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

/// Longest request line plus headers hyper buffers.
const MAX_HEADER_BUFFER: usize = 32 * 1024;

struct Shared {
    state: Arc<AppState>,
    sink: Arc<dyn LogSink>,
    counter: AtomicU64,
    epoch: u64,
}

#[derive(Clone)]
struct Conn {
    shared: Arc<Shared>,
    peer: SocketAddr,
    inner: TowerToHyperService<axum::Router>,
}

/// Makes sure a request that is dropped without an answer (client left) is still logged.
struct Abandoned(Arc<RequestScope>, bool);

impl Drop for Abandoned {
    fn drop(&mut self) {
        if !self.1 {
            self.0.finish(499, Some("client_gone"));
        }
    }
}

impl Service<Request<Incoming>> for Conn {
    type Response = Response<Body>;
    type Error = Infallible;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Infallible>> + Send>>;

    fn call(&self, mut request: Request<Incoming>) -> Self::Future {
        let shared = self.shared.clone();
        let inner = self.inner.clone();
        let peer = self.peer;
        Box::pin(async move {
            let n = shared.counter.fetch_add(1, Ordering::Relaxed);
            let id = format!("{:x}-{n:06x}", shared.epoch);
            let forwarded = request
                .headers()
                .get_all("x-forwarded-for")
                .iter()
                .filter_map(|v| v.to_str().ok())
                .collect::<Vec<_>>();
            let client = shared
                .state
                .config
                .trusted_proxies
                .client_ip(peer.ip(), forwarded);
            let scope = Arc::new(RequestScope::new(
                id.clone(),
                request.method().as_str().to_owned(),
                client,
                shared.sink.clone(),
            ));
            request.extensions_mut().insert(scope.clone());
            let mut abandoned = Abandoned(scope.clone(), false);
            let result = inner.call(request).await;
            abandoned.1 = true;
            let mut response = match result {
                Ok(r) => r,
                Err(never) => match never {},
            };
            if response.extensions().get::<Deferred>().is_none() {
                scope.finish(response.status().as_u16(), None);
            }
            if let Ok(v) = HeaderValue::from_str(&id) {
                response.headers_mut().insert("x-request-id", v);
            }
            Ok(response)
        })
    }
}

/// Serves on `listener` until `shutdown` completes, then waits up to the configured grace for open connections.
pub async fn serve(
    listener: TcpListener,
    state: Arc<AppState>,
    sink: Arc<dyn LogSink>,
    shutdown: impl Future<Output = ()>,
) -> std::io::Result<()> {
    let config = state.config.clone();
    let epoch = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    let shared = Arc::new(Shared {
        state: state.clone(),
        sink,
        counter: AtomicU64::new(0),
        epoch,
    });
    let app = router(state);
    let slots = Arc::new(Semaphore::new(config.max_connections));
    let mut tasks = JoinSet::new();
    tokio::pin!(shutdown);
    loop {
        tokio::select! {
            () = &mut shutdown => break,
            accepted = listener.accept() => {
                let Ok((stream, peer)) = accepted else { continue };
                let Ok(permit) = slots.clone().try_acquire_owned() else {
                    drop(stream); // over the connection limit: shed the connection
                    continue;
                };
                let conn = Conn {
                    shared: shared.clone(),
                    peer,
                    inner: TowerToHyperService::new(app.clone()),
                };
                let header_timeout = config.header_timeout;
                tasks.spawn(async move {
                    let mut builder = hyper::server::conn::http1::Builder::new();
                    builder
                        .timer(TokioTimer::new())
                        .header_read_timeout(header_timeout)
                        .max_buf_size(MAX_HEADER_BUFFER);
                    let _ = builder.serve_connection(TokioIo::new(stream), conn).await;
                    drop(permit);
                });
            }
            Some(_) = tasks.join_next(), if !tasks.is_empty() => {}
        }
    }
    drop(listener);
    let drain = async { while tasks.join_next().await.is_some() {} };
    let _ = tokio::time::timeout(config.shutdown_grace, drain).await;
    tasks.abort_all();
    Ok(())
}
