//! Interrupt handle: one clone stays with the loop, one goes into the call. Triggering it ends the call at once,
//! whether it is connecting, waiting to retry or reading a stream.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::sync::Notify;

/// Shared interrupt flag.
#[derive(Debug, Clone, Default)]
pub struct Interrupt {
    inner: Arc<Inner>,
}

#[derive(Debug, Default)]
struct Inner {
    set: AtomicBool,
    notify: Notify,
}

impl Interrupt {
    /// A fresh, untriggered handle.
    pub fn new() -> Self {
        Self::default()
    }

    /// Interrupts every call that holds a clone of this handle.
    pub fn trigger(&self) {
        self.inner.set.store(true, Ordering::SeqCst);
        self.inner.notify.notify_waiters();
    }

    /// Whether it has been triggered.
    pub fn is_triggered(&self) -> bool {
        self.inner.set.load(Ordering::SeqCst)
    }

    /// Completes when the handle is triggered (immediately if it already was).
    pub async fn triggered(&self) {
        loop {
            let waiting = self.inner.notify.notified();
            if self.is_triggered() {
                return;
            }
            waiting.await;
        }
    }
}
