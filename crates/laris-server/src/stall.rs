//! Write-stall guard (SR-S1, slow reader): a connection whose writes stay blocked longer than the limit fails
//! with `TimedOut`, so a client that stops reading the answer cannot hold a connection slot for ever.
//!
//! The clock runs only while a write or flush is blocked by the peer. Time spent waiting for the model, or for
//! the next request, is not counted, and every write that makes progress restarts it.

use std::future::Future;
use std::io::{self, IoSlice};
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::time::Sleep;

/// A stream that gives up on a write blocked for `stall`.
pub struct StallGuard<S> {
    inner: S,
    stall: Duration,
    timer: Option<Pin<Box<Sleep>>>,
}

impl<S> StallGuard<S> {
    /// Wraps `inner`.
    pub fn new(inner: S, stall: Duration) -> Self {
        Self {
            inner,
            stall,
            timer: None,
        }
    }

    fn blocked<T>(&mut self, cx: &mut Context<'_>) -> Poll<io::Result<T>> {
        let stall = self.stall;
        let timer = self
            .timer
            .get_or_insert_with(|| Box::pin(tokio::time::sleep(stall)));
        match timer.as_mut().poll(cx) {
            Poll::Ready(()) => Poll::Ready(Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "the peer stopped reading",
            ))),
            Poll::Pending => Poll::Pending,
        }
    }
}

impl<S: AsyncRead + Unpin> AsyncRead for StallGuard<S> {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_read(cx, buf)
    }
}

impl<S: AsyncWrite + Unpin> AsyncWrite for StallGuard<S> {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        match Pin::new(&mut self.inner).poll_write(cx, buf) {
            Poll::Pending => self.blocked(cx),
            ready => {
                self.timer = None;
                ready
            }
        }
    }

    fn poll_write_vectored(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bufs: &[IoSlice<'_>],
    ) -> Poll<io::Result<usize>> {
        match Pin::new(&mut self.inner).poll_write_vectored(cx, bufs) {
            Poll::Pending => self.blocked(cx),
            ready => {
                self.timer = None;
                ready
            }
        }
    }

    fn is_write_vectored(&self) -> bool {
        self.inner.is_write_vectored()
    }

    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        match Pin::new(&mut self.inner).poll_flush(cx) {
            Poll::Pending => self.blocked(cx),
            ready => {
                self.timer = None;
                ready
            }
        }
    }

    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_shutdown(cx)
    }
}
