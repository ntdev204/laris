//! The dense channel: an interface only. The vectors come from the model block; until stage 1 passes G12 no dense
//! channel is qualified, and every fused answer that used one says so (see [`crate::Fused::unqualified_channels`]).

/// One dense hit: an identifier (a note path) and a similarity, higher is closer.
#[derive(Debug, Clone, PartialEq)]
pub struct DenseHit {
    /// Identifier of the item, a vault-relative path.
    pub id: String,
    /// Cosine similarity or another score where larger means closer.
    pub score: f64,
}

/// A source of dense hits. An implementation does not choose its own qualification: [`DenseChannel::qualified`]
/// stays `false` until the owner records that the embedding model passed its gate.
pub trait DenseChannel {
    /// Name used in provenance and reports.
    fn name(&self) -> &str;
    /// True only when the embedding model behind the channel passed G12.
    fn qualified(&self) -> bool {
        false
    }
    /// The best `k` items for `query`, closest first, ties by id ascending.
    fn search(&self, query: &str, k: usize) -> Vec<DenseHit>;
}

/// The absent channel: finds nothing. The default while the model block provides no embedding.
#[derive(Debug, Default, Clone, Copy)]
pub struct NoDense;

impl DenseChannel for NoDense {
    fn name(&self) -> &str {
        "dense"
    }

    fn search(&self, _query: &str, _k: usize) -> Vec<DenseHit> {
        Vec::new()
    }
}
