//! Monthly partitions, the daily usage summary and retention (SR-S3).
//!
//! `ensure_partitions` makes sure the previous, this and the next months have partitions; `summarise` writes one
//! `usage_daily` row per key and UTC day from the raw rows; `purge` drops whole partitions that lie entirely before
//! the retention cutoff (usage only after its days are summarised) and deletes the older rows of the month that
//! straddles it. Every step runs under an advisory lock, so several server processes can run it at once.
//! Timestamps are seconds since the epoch.

use super::{Storage, StorageError};
use sqlx::Row;
use sqlx::postgres::PgPool;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::watch;

const LOCK: i64 = 7_260_002;
const PARENTS: [&str; 2] = ["usage", "traces"];

/// Seconds since the epoch now.
pub(crate) fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// Days since 1970-01-01 of a civil date (proleptic Gregorian).
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// Civil date of a day count since 1970-01-01.
fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Month of a timestamp as `year * 12 + month - 1` in UTC.
pub(crate) fn month_index(ts: f64) -> i64 {
    let (y, m, _) = civil_from_days((ts / 86_400.0).floor() as i64);
    y * 12 + m - 1
}

/// First second of the month with this index.
fn month_start(index: i64) -> f64 {
    (days_from_civil(index.div_euclid(12), index.rem_euclid(12) + 1, 1) * 86_400) as f64
}

/// The upper bound of the partition `parent_YYYYMM`, or `None` when the name is not one of ours.
fn upper_bound(parent: &str, name: &str) -> Option<f64> {
    let tail = name.strip_prefix(parent)?.strip_prefix('_')?;
    if tail.len() != 6 || !tail.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let year: i64 = tail[..4].parse().ok()?;
    let month: i64 = tail[4..].parse().ok()?;
    if !(1..=12).contains(&month) {
        return None;
    }
    Some(month_start(year * 12 + month))
}

/// One row of the daily summary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DailyUsage {
    /// UTC day, `YYYY-MM-DD`.
    pub day: String,
    /// Key the usage belongs to.
    pub key_id: String,
    /// Requests that day.
    pub requests: i64,
    /// Prompt tokens that day.
    pub prompt_tokens: i64,
    /// Completion tokens that day.
    pub completion_tokens: i64,
}

/// What `purge` removed.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PurgeReport {
    /// Partitions dropped whole.
    pub dropped: Vec<String>,
    /// Rows deleted from the month that straddles the cutoff.
    pub rows_deleted: u64,
}

/// What one maintenance round did.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RunReport {
    /// Partitions that exist after the round for the months looked at.
    pub partitions: Vec<String>,
    /// Summary rows written.
    pub summarised: u64,
    /// Retention result.
    pub purge: PurgeReport,
}

/// Partition, summary and retention work on one pool.
#[derive(Clone)]
pub struct Maintenance {
    pool: PgPool,
    usage_retention_days: f64,
    trace_retention_days: f64,
}

impl Maintenance {
    /// Maintenance with the given retention in days.
    pub fn new(pool: PgPool, usage_retention_days: f64, trace_retention_days: f64) -> Self {
        Self {
            pool,
            usage_retention_days,
            trace_retention_days,
        }
    }

    /// Makes the partitions of the month before `now`, of `now` and of the next `months_ahead` months; returns
    /// their names.
    pub async fn ensure_partitions(
        &self,
        now: f64,
        months_ahead: i64,
    ) -> Result<Vec<String>, StorageError> {
        let mut tx = self.pool.begin().await?;
        sqlx::query("SELECT pg_advisory_xact_lock($1)")
            .bind(LOCK)
            .execute(&mut *tx)
            .await?;
        let this = month_index(now);
        let mut made = Vec::new();
        for add in -1..=months_ahead {
            let stamp = month_start(this + add);
            for parent in PARENTS {
                let row = sqlx::query(
                    "SELECT laris_month_partition($1::text, $2::double precision) AS p",
                )
                .bind(parent)
                .bind(stamp)
                .fetch_one(&mut *tx)
                .await?;
                made.push(row.try_get::<String, _>("p")?);
            }
        }
        tx.commit().await?;
        Ok(made)
    }

    /// Names of the partitions of `parent` (`usage` or `traces`) in this schema, in order.
    pub async fn partitions(&self, parent: &str) -> Result<Vec<String>, StorageError> {
        let rows = sqlx::query(
            "SELECT c.relname::text AS name FROM pg_inherits i \
             JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent \
             WHERE p.relname = $1 AND p.relnamespace = current_schema()::regnamespace ORDER BY c.relname",
        )
        .bind(parent)
        .fetch_all(&self.pool)
        .await?;
        rows.iter()
            .map(|r| Ok(r.try_get::<String, _>("name")?))
            .collect()
    }

    /// Rebuilds the summary from the last summarised day (inclusive) up to `now`; returns the rows written.
    pub async fn summarise(&self, now: f64) -> Result<u64, StorageError> {
        let mut tx = self.pool.begin().await?;
        sqlx::query("SELECT pg_advisory_xact_lock($1)")
            .bind(LOCK)
            .execute(&mut *tx)
            .await?;
        let last: Option<String> = sqlx::query_scalar("SELECT MAX(day) FROM usage_daily")
            .fetch_one(&mut *tx)
            .await?;
        let since = last.as_deref().and_then(day_start).unwrap_or(0.0);
        let done = sqlx::query(
            "INSERT INTO usage_daily (day, key_id, requests, prompt_tokens, completion_tokens) \
             SELECT to_char(to_timestamp(ts) AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day, key_id, COUNT(*), \
             SUM(prompt_tokens), SUM(completion_tokens) FROM usage WHERE ts >= $1 AND ts <= $2 GROUP BY 1, 2 \
             ON CONFLICT (day, key_id) DO UPDATE SET requests = EXCLUDED.requests, \
             prompt_tokens = EXCLUDED.prompt_tokens, completion_tokens = EXCLUDED.completion_tokens",
        )
        .bind(since)
        .bind(now)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;
        Ok(done.rows_affected())
    }

    /// The summary rows from `since_day` (`YYYY-MM-DD`) on, ordered by day and key.
    pub async fn daily(&self, since_day: &str) -> Result<Vec<DailyUsage>, StorageError> {
        let rows = sqlx::query(
            "SELECT day, key_id, requests, prompt_tokens, completion_tokens FROM usage_daily \
             WHERE day >= $1 ORDER BY day, key_id",
        )
        .bind(since_day)
        .fetch_all(&self.pool)
        .await?;
        rows.iter()
            .map(|r| {
                Ok(DailyUsage {
                    day: r.try_get("day")?,
                    key_id: r.try_get("key_id")?,
                    requests: r.try_get("requests")?,
                    prompt_tokens: r.try_get("prompt_tokens")?,
                    completion_tokens: r.try_get("completion_tokens")?,
                })
            })
            .collect()
    }

    /// Drops partitions that lie wholly before the retention cutoff and deletes the older rows of the month that
    /// straddles it. Usage days are summarised first, so the summary outlives the raw rows.
    pub async fn purge(&self, now: f64) -> Result<PurgeReport, StorageError> {
        let mut report = PurgeReport::default();
        for (parent, days) in [
            ("usage", self.usage_retention_days),
            ("traces", self.trace_retention_days),
        ] {
            let cutoff = now - days * 86_400.0;
            if parent == "usage" {
                self.summarise(now).await?;
            }
            for name in self.partitions(parent).await? {
                if upper_bound(parent, &name).is_some_and(|upper| upper <= cutoff) {
                    sqlx::raw_sql(&format!("DROP TABLE IF EXISTS \"{name}\""))
                        .execute(&self.pool)
                        .await?;
                    report.dropped.push(name);
                }
            }
            let sql = format!("DELETE FROM {parent} WHERE ts < $1");
            report.rows_deleted += sqlx::query(&sql)
                .bind(cutoff)
                .execute(&self.pool)
                .await?
                .rows_affected();
        }
        Ok(report)
    }

    /// One whole round: partitions, summary, retention.
    pub async fn run_once(&self, now: f64) -> Result<RunReport, StorageError> {
        Ok(RunReport {
            partitions: self.ensure_partitions(now, 2).await?,
            summarised: self.summarise(now).await?,
            purge: self.purge(now).await?,
        })
    }
}

/// First second of a `YYYY-MM-DD` day.
fn day_start(day: &str) -> Option<f64> {
    let mut parts = day.split('-');
    let y: i64 = parts.next()?.parse().ok()?;
    let m: i64 = parts.next()?.parse().ok()?;
    let d: i64 = parts.next()?.parse().ok()?;
    Some((days_from_civil(y, m, d) * 86_400) as f64)
}

/// A running retention task; stop it with [`RetentionHandle::stop`].
pub struct RetentionHandle {
    stop: watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
}

impl RetentionHandle {
    /// Runs a round now and then every `interval`; a failed round is kept in
    /// [`Storage::last_retention_error`] and the next one tries again.
    pub fn spawn(storage: Arc<Storage>, interval: Duration) -> Self {
        let (stop, mut stopped) = watch::channel(false);
        let task = tokio::spawn(async move {
            loop {
                let result = storage.maintenance().run_once(now_secs()).await;
                storage.set_retention_error(result.err().map(|e| e.to_string()));
                tokio::select! {
                    _ = tokio::time::sleep(interval) => {}
                    _ = stopped.changed() => return,
                }
            }
        });
        Self { stop, task }
    }

    /// Stops the task and waits for it.
    pub async fn stop(self) {
        let _ = self.stop.send(true);
        let _ = self.task.await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn civil_round_trip_and_month_bounds() {
        assert_eq!(days_from_civil(1970, 1, 1), 0);
        assert_eq!(
            civil_from_days(days_from_civil(2026, 11, 18)),
            (2026, 11, 18)
        );
        assert_eq!(civil_from_days(days_from_civil(2024, 2, 29)), (2024, 2, 29));
        // 2026-11-18 12:00:00 UTC
        let ts = (days_from_civil(2026, 11, 18) * 86_400 + 43_200) as f64;
        assert_eq!(
            month_start(month_index(ts)),
            (days_from_civil(2026, 11, 1) * 86_400) as f64
        );
        assert_eq!(
            month_start(month_index(ts) + 2),
            (days_from_civil(2027, 1, 1) * 86_400) as f64
        );
        assert_eq!(month_index(-1.0), 1969 * 12 + 11);
    }

    #[test]
    fn partition_names_give_their_upper_bound() {
        let dec = (days_from_civil(2027, 1, 1) * 86_400) as f64;
        assert_eq!(upper_bound("usage", "usage_202612"), Some(dec));
        assert_eq!(upper_bound("usage", "traces_202612"), None);
        assert_eq!(upper_bound("usage", "usage_2026"), None);
        assert_eq!(upper_bound("usage", "usage_202613"), None);
        assert_eq!(upper_bound("usage", "usage_20261x"), None);
    }

    #[test]
    fn day_start_reads_a_summary_day() {
        assert_eq!(day_start("1970-01-02"), Some(86_400.0));
        assert_eq!(day_start("nonsense"), None);
    }
}
