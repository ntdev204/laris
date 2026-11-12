-- usage and traces become tables partitioned by month on `ts` (seconds since the epoch, UTC).
-- A month's partition is created by laris_month_partition(); a retention task drops old ones.

CREATE FUNCTION laris_month_partition(parent TEXT, at_ts DOUBLE PRECISION) RETURNS TEXT AS $$
DECLARE
    month_start TIMESTAMP := date_trunc('month', to_timestamp(at_ts) AT TIME ZONE 'UTC');
    lower_bound DOUBLE PRECISION := extract(epoch FROM (month_start AT TIME ZONE 'UTC'));
    upper_bound DOUBLE PRECISION :=
        extract(epoch FROM ((month_start + interval '1 month') AT TIME ZONE 'UTC'));
    part TEXT := parent || '_' || to_char(month_start, 'YYYYMM');
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        part, parent, lower_bound, upper_bound);
    RETURN part;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE usage RENAME TO usage_old;
ALTER INDEX usage_key_ts RENAME TO usage_old_key_ts;
ALTER TABLE traces RENAME TO traces_old;
ALTER INDEX traces_key_ts RENAME TO traces_old_key_ts;

CREATE SEQUENCE usage_seq;
CREATE TABLE usage (
    id BIGINT NOT NULL DEFAULT nextval('usage_seq'),
    key_id TEXT NOT NULL,
    ts DOUBLE PRECISION NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'chat',
    prompt_tokens BIGINT NOT NULL DEFAULT 0,
    completion_tokens BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);
CREATE INDEX usage_key_ts ON usage (key_id, ts);

CREATE SEQUENCE traces_seq;
CREATE TABLE traces (
    id BIGINT NOT NULL DEFAULT nextval('traces_seq'),
    key_id TEXT NOT NULL,
    ts DOUBLE PRECISION NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_sha256 TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    tool_calls TEXT NOT NULL DEFAULT '[]',
    brain TEXT NOT NULL DEFAULT '[]',
    answer_chars INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);
CREATE INDEX traces_key_ts ON traces (key_id, ts);

-- rows written before partitioning move into the partitions of their months
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT DISTINCT ts FROM (SELECT ts FROM usage_old UNION ALL SELECT ts FROM traces_old) t
    LOOP
        PERFORM laris_month_partition('usage', r.ts);
        PERFORM laris_month_partition('traces', r.ts);
    END LOOP;
    INSERT INTO usage (id, key_id, ts, session_id, kind, prompt_tokens, completion_tokens)
        SELECT id, key_id, ts, session_id, kind, prompt_tokens, completion_tokens FROM usage_old;
    INSERT INTO traces (id, key_id, ts, session_id, model, prompt_sha256, task, reasoning,
                        tool_calls, brain, answer_chars)
        SELECT id, key_id, ts, session_id, model, prompt_sha256, task, reasoning,
               tool_calls, brain, answer_chars FROM traces_old;
    PERFORM setval('usage_seq', COALESCE((SELECT max(id) FROM usage_old), 0) + 1, false);
    PERFORM setval('traces_seq', COALESCE((SELECT max(id) FROM traces_old), 0) + 1, false);
END;
$$;
DROP TABLE usage_old;
DROP TABLE traces_old;

-- one row per key and UTC day, kept after the raw rows are gone
CREATE TABLE usage_daily (
    day TEXT NOT NULL,
    key_id TEXT NOT NULL,
    requests BIGINT NOT NULL,
    prompt_tokens BIGINT NOT NULL,
    completion_tokens BIGINT NOT NULL,
    PRIMARY KEY (day, key_id)
);
