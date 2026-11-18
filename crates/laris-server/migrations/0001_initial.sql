CREATE TABLE keys (
    id TEXT PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE,
    secret_enc BYTEA,
    label TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    extra_permissions TEXT NOT NULL DEFAULT '[]',
    token_limit BIGINT,
    tokens_used BIGINT NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION,
    revoked_at DOUBLE PRECISION,
    last_used_at DOUBLE PRECISION,
    allowed_ips TEXT NOT NULL DEFAULT '[]',
    builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE usage (
    id BIGSERIAL PRIMARY KEY,
    key_id TEXT NOT NULL,
    ts DOUBLE PRECISION NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'chat',
    prompt_tokens BIGINT NOT NULL DEFAULT 0,
    completion_tokens BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX usage_key_ts ON usage (key_id, ts);

CREATE TABLE traces (
    id BIGSERIAL PRIMARY KEY,
    key_id TEXT NOT NULL,
    ts DOUBLE PRECISION NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_sha256 TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    tool_calls TEXT NOT NULL DEFAULT '[]',
    brain TEXT NOT NULL DEFAULT '[]',
    answer_chars INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX traces_key_ts ON traces (key_id, ts);
