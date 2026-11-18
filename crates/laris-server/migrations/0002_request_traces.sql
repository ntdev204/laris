-- T150: one content-free row per request in `traces` (kind 'request'). The reasoning rows of SR-S4 keep kind
-- 'reasoning'. Tool names go in tool_calls and brain note ids in brain (both JSON arrays of short names).
ALTER TABLE traces ADD COLUMN kind TEXT NOT NULL DEFAULT 'reasoning';
ALTER TABLE traces ADD COLUMN request_id TEXT NOT NULL DEFAULT '';
ALTER TABLE traces ADD COLUMN route TEXT NOT NULL DEFAULT '';
ALTER TABLE traces ADD COLUMN status INTEGER NOT NULL DEFAULT 0;
ALTER TABLE traces ADD COLUMN outcome TEXT NOT NULL DEFAULT '';
ALTER TABLE traces ADD COLUMN duration_ms BIGINT NOT NULL DEFAULT 0;
ALTER TABLE traces ADD COLUMN prompt_tokens BIGINT NOT NULL DEFAULT 0;
ALTER TABLE traces ADD COLUMN completion_tokens BIGINT NOT NULL DEFAULT 0;
CREATE INDEX traces_kind_ts ON traces (kind, ts);
