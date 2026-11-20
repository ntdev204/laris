-- T239: the pipeline stages of a request (stage, outcome, milliseconds, rule or reason code) as a JSON array, never text.
ALTER TABLE traces ADD COLUMN stages TEXT NOT NULL DEFAULT '[]';
