--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: __schema__; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA __schema__;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: keys; Type: TABLE; Schema: __schema__; Owner: -
--

CREATE TABLE __schema__.keys (
    id text NOT NULL,
    digest text NOT NULL,
    secret_enc bytea,
    label text DEFAULT ''::text NOT NULL,
    role text NOT NULL,
    extra_permissions text DEFAULT '[]'::text NOT NULL,
    token_limit bigint,
    tokens_used bigint DEFAULT 0 NOT NULL,
    created_at double precision NOT NULL,
    expires_at double precision,
    revoked_at double precision,
    last_used_at double precision,
    allowed_ips text DEFAULT '[]'::text NOT NULL,
    builtin integer DEFAULT 0 NOT NULL,
    tokens_reserved bigint DEFAULT 0 NOT NULL
);


--
-- Name: schema_version; Type: TABLE; Schema: __schema__; Owner: -
--

CREATE TABLE __schema__.schema_version (
    version integer NOT NULL,
    name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now()
);


--
-- Name: traces; Type: TABLE; Schema: __schema__; Owner: -
--

CREATE TABLE __schema__.traces (
    id bigint NOT NULL,
    key_id text NOT NULL,
    ts double precision NOT NULL,
    session_id text DEFAULT ''::text NOT NULL,
    model text DEFAULT ''::text NOT NULL,
    prompt_sha256 text DEFAULT ''::text NOT NULL,
    task text DEFAULT ''::text NOT NULL,
    reasoning text DEFAULT ''::text NOT NULL,
    tool_calls text DEFAULT '[]'::text NOT NULL,
    brain text DEFAULT '[]'::text NOT NULL,
    answer_chars integer DEFAULT 0 NOT NULL
);


--
-- Name: traces_id_seq; Type: SEQUENCE; Schema: __schema__; Owner: -
--

CREATE SEQUENCE __schema__.traces_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: traces_id_seq; Type: SEQUENCE OWNED BY; Schema: __schema__; Owner: -
--

ALTER SEQUENCE __schema__.traces_id_seq OWNED BY __schema__.traces.id;


--
-- Name: usage; Type: TABLE; Schema: __schema__; Owner: -
--

CREATE TABLE __schema__.usage (
    id bigint NOT NULL,
    key_id text NOT NULL,
    ts double precision NOT NULL,
    session_id text DEFAULT ''::text NOT NULL,
    kind text DEFAULT 'chat'::text NOT NULL,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL
);


--
-- Name: usage_id_seq; Type: SEQUENCE; Schema: __schema__; Owner: -
--

CREATE SEQUENCE __schema__.usage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: usage_id_seq; Type: SEQUENCE OWNED BY; Schema: __schema__; Owner: -
--

ALTER SEQUENCE __schema__.usage_id_seq OWNED BY __schema__.usage.id;


--
-- Name: traces id; Type: DEFAULT; Schema: __schema__; Owner: -
--

ALTER TABLE ONLY __schema__.traces ALTER COLUMN id SET DEFAULT nextval('__schema__.traces_id_seq'::regclass);


--
-- Name: usage id; Type: DEFAULT; Schema: __schema__; Owner: -
--

ALTER TABLE ONLY __schema__.usage ALTER COLUMN id SET DEFAULT nextval('__schema__.usage_id_seq'::regclass);


--
-- Data for Name: keys; Type: TABLE DATA; Schema: __schema__; Owner: -
--

INSERT INTO __schema__.keys (id, digest, secret_enc, label, role, extra_permissions, token_limit, tokens_used, created_at, expires_at, revoked_at, last_used_at, allowed_ips, builtin, tokens_reserved) VALUES ('k1', 'd1', NULL, 'admin key', 'admin', '[]', NULL, 120, 1760000000, NULL, NULL, NULL, '[]', 0, 0);
INSERT INTO __schema__.keys (id, digest, secret_enc, label, role, extra_permissions, token_limit, tokens_used, created_at, expires_at, revoked_at, last_used_at, allowed_ips, builtin, tokens_reserved) VALUES ('k2', 'd2', NULL, 'user key', 'user', '[]', 1000000, 5000, 1760000100, NULL, NULL, NULL, '[]', 0, 40);


--
-- Data for Name: schema_version; Type: TABLE DATA; Schema: __schema__; Owner: -
--

INSERT INTO __schema__.schema_version (version, name, applied_at) VALUES (1, '0001_initial.sql', '2026-11-18 13:48:07.67524+00');
INSERT INTO __schema__.schema_version (version, name, applied_at) VALUES (2, '0002_reserved_tokens.sql', '2026-11-18 13:48:07.67524+00');


--
-- Data for Name: traces; Type: TABLE DATA; Schema: __schema__; Owner: -
--

INSERT INTO __schema__.traces (id, key_id, ts, session_id, model, prompt_sha256, task, reasoning, tool_calls, brain, answer_chars) VALUES (1, 'k1', 1786000000, 's1', 'm', 'abc', 'task one', 'reasoning one', '[]', '["n1"]', 11);
INSERT INTO __schema__.traces (id, key_id, ts, session_id, model, prompt_sha256, task, reasoning, tool_calls, brain, answer_chars) VALUES (2, 'k2', 1791400000, 's3', 'm', 'def', 'task two', 'reasoning two', '["t"]', '[]', 22);


--
-- Data for Name: usage; Type: TABLE DATA; Schema: __schema__; Owner: -
--

INSERT INTO __schema__.usage (id, key_id, ts, session_id, kind, prompt_tokens, completion_tokens) VALUES (1, 'k1', 1786000000, 's1', 'chat', 10, 20);
INSERT INTO __schema__.usage (id, key_id, ts, session_id, kind, prompt_tokens, completion_tokens) VALUES (2, 'k2', 1788700000, 's2', 'chat', 30, 40);
INSERT INTO __schema__.usage (id, key_id, ts, session_id, kind, prompt_tokens, completion_tokens) VALUES (3, 'k2', 1788700100, 's2', 'embed', 5, 0);
INSERT INTO __schema__.usage (id, key_id, ts, session_id, kind, prompt_tokens, completion_tokens) VALUES (4, 'k2', 1791400000, 's3', 'chat', 7, 9);


--
-- Name: traces_id_seq; Type: SEQUENCE SET; Schema: __schema__; Owner: -
--

SELECT pg_catalog.setval('__schema__.traces_id_seq', 2, true);


--
-- Name: usage_id_seq; Type: SEQUENCE SET; Schema: __schema__; Owner: -
--

SELECT pg_catalog.setval('__schema__.usage_id_seq', 4, true);


--
-- Name: keys keys_digest_key; Type: CONSTRAINT; Schema: __schema__; Owner: -
--

ALTER TABLE ONLY __schema__.keys
    ADD CONSTRAINT keys_digest_key UNIQUE (digest);


--
-- Name: keys keys_pkey; Type: CONSTRAINT; Schema: __schema__; Owner: -
--

ALTER TABLE ONLY __schema__.keys
    ADD CONSTRAINT keys_pkey PRIMARY KEY (id);


--
-- Name: schema_version schema_version_pkey; Type: CONSTRAINT; Schema: __schema__; Owner: -
--

ALTER TABLE ONLY __schema__.schema_version
    ADD CONSTRAINT schema_version_pkey PRIMARY KEY (version);


--
-- Name: traces traces_pkey; Type: CONSTRAINT; Schema: __schema__; Owner: -
--

ALTER TABLE ONLY __schema__.traces
    ADD CONSTRAINT traces_pkey PRIMARY KEY (id);


--
-- Name: usage usage_pkey; Type: CONSTRAINT; Schema: __schema__; Owner: -
--

ALTER TABLE ONLY __schema__.usage
    ADD CONSTRAINT usage_pkey PRIMARY KEY (id);


--
-- Name: traces_key_ts; Type: INDEX; Schema: __schema__; Owner: -
--

CREATE INDEX traces_key_ts ON __schema__.traces USING btree (key_id, ts);


--
-- Name: usage_key_ts; Type: INDEX; Schema: __schema__; Owner: -
--

CREATE INDEX usage_key_ts ON __schema__.usage USING btree (key_id, ts);


--
-- PostgreSQL database dump complete
--


