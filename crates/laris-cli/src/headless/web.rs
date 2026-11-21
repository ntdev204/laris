//! The network behind `WebFetch` and `WebSearch` (T255, SR-H17): public pages only, through the client's own address.

use laris_model_client::WebClient;
use laris_tools::{Page, ToolError, WebTransport};
use std::sync::Arc;
use tokio::runtime::Runtime;

/// Lets the sync tools use the async web client.
pub struct WebBridge {
    /// The client.
    pub client: WebClient,
    /// The runtime the client's requests run on.
    pub runtime: Arc<Runtime>,
}

impl WebTransport for WebBridge {
    fn get(&self, url: &str, accept: &str) -> Result<Page, ToolError> {
        let page = self
            .runtime
            .block_on(self.client.get(url, accept))
            .map_err(|e| ToolError::new(e.code, e.message))?;
        Ok(Page {
            status: page.status,
            url: page.url,
            content_type: page.content_type,
            body: page.body,
            truncated: page.truncated,
        })
    }
}
