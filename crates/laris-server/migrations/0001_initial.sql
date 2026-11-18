-- LARIS server schema. usage and traces are partitioned by month on `ts` (seconds since the epoch, UTC).
-- A month's partition is created by laris_month_partition(); a retention task drops old ones.

CREATE TABLE keys (
    id TEXT PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE,
    secret_enc BYTEA,
    label TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    extra_permissions TEXT NOT NULL DEFAULT '[]',
    token_limit BIGINT,
    tokens_used BIGINT NOT NULL DEFAULT 0,
    tokens_reserved BIGINT NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION,
    revoked_at DOUBLE PRECISION,
    last_used_at DOUBLE PRECISION,
    allowed_ips TEXT NOT NULL DEFAULT '[]',
    builtin INTEGER NOT NULL DEFAULT 0
);

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

-- one row per key and UTC day, kept after the raw rows are gone
CREATE TABLE usage_daily (
    day TEXT NOT NULL,
    key_id TEXT NOT NULL,
    requests BIGINT NOT NULL,
    prompt_tokens BIGINT NOT NULL,
    completion_tokens BIGINT NOT NULL,
    PRIMARY KEY (day, key_id)
);
