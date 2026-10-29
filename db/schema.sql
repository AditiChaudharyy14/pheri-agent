-- Pheri database schema (Postgres 15+, Neon).
--
-- Run once on a fresh database (or a fresh schema: everything here follows search_path).
-- Every tenant table carries business_id and is locked to the business named in the
-- setting `app.business_id`. Set it inside each transaction, never for the session:
--
--     BEGIN;
--     SET LOCAL ROLE pheri_app;
--     SELECT set_config('app.business_id', '<business uuid>', true);   -- true = this transaction only
--     ...
--     COMMIT;
--
-- Neon's pooled endpoint (PgBouncer, transaction mode) shares server sessions between clients,
-- so a session-level SET or set_config(..., false) leaks to the next client: another business.
-- If the setting is missing or empty, every tenant table returns no rows (fails closed).
--
-- FORCE ROW LEVEL SECURITY applies the policies to the table owner too, unless that role has
-- BYPASSRLS, and Neon's neondb_owner does. So the app never runs queries as the owner: it runs
-- as `pheri_app`, which owns nothing and cannot bypass RLS. The login user is created in the
-- Neon console and granted pheri_app; no password lives here.

BEGIN;

-- ---- the app role ----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pheri_app') THEN
        CREATE ROLE pheri_app NOLOGIN NOBYPASSRLS;
    END IF;
END $$;

-- The current tenant, or NULL when unset. A malformed value raises instead of matching.
CREATE FUNCTION app_business_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT NULLIF(current_setting('app.business_id', true), '')::uuid $$;

-- ---- tenants ---------------------------------------------------------------------
CREATE TABLE businesses (
    id          uuid PRIMARY KEY,
    slug        text NOT NULL UNIQUE,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Fixed ids so every demo run is identical (same values as pheri.synth.BUSINESS_IDS).
-- Seeded before RLS is switched on below.
INSERT INTO businesses (id, slug, name) VALUES
    ('b5d1e5c0-0000-4000-8000-000000000001', 'brightdesk', 'Brightdesk'),
    ('ce771e00-0000-4000-8000-000000000002', 'birgunj', 'Birgunj Saree Ghar');

-- ---- customers and what we know about them ---------------------------------------
CREATE TABLE customers (
    id           uuid NOT NULL DEFAULT gen_random_uuid(),
    business_id  uuid NOT NULL REFERENCES businesses (id),
    external_id  text,                          -- id in the business's own system, if any
    email        text,                          -- normalised: trimmed, lower-case
    name         text,
    company      text,
    attrs        jsonb NOT NULL DEFAULT '{}',   -- plan, seats, country, ...
    identities   jsonb NOT NULL DEFAULT '[]',   -- every raw spelling seen, with its source
    do_not_contact         boolean NOT NULL DEFAULT false,  -- they said stop: no customer-facing action
    do_not_contact_at      timestamptz,
    do_not_contact_source  text,                -- the reply that asked, e.g. M0123
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (business_id, id),                   -- lets child tables pin rows to one tenant
    UNIQUE (business_id, email)
);

CREATE TABLE events (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    business_id  uuid NOT NULL,
    customer_id  uuid NOT NULL,
    ts           timestamptz NOT NULL,
    type         text NOT NULL,
    props        jsonb NOT NULL DEFAULT '{}',
    source_ref   text,                          -- e.g. events.jsonl#L15654
    FOREIGN KEY (business_id, customer_id) REFERENCES customers (business_id, id)
);
CREATE INDEX events_customer_ts ON events (business_id, customer_id, ts DESC);

-- Tickets, DMs, emails, chat, sales notes and Pheri's own outbound replies.
CREATE TABLE messages (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id  uuid NOT NULL,
    customer_id  uuid,                          -- NULL until identity is resolved
    source_id    text NOT NULL,                 -- T0999, M0001, sales_notes.txt#L41, ...
    channel      text NOT NULL CHECK (channel IN ('ticket', 'email', 'instagram_dm', 'chat', 'sales_note')),
    direction    text NOT NULL CHECK (direction IN ('inbound', 'outbound', 'internal')),
    subject      text,
    body         text NOT NULL,
    lang         text,
    status       text,
    created_at   timestamptz NOT NULL,
    UNIQUE (business_id, source_id),
    FOREIGN KEY (business_id, customer_id) REFERENCES customers (business_id, id)
);

-- One profile per customer: facts computed in code, insights read by the model and
-- checked in code, and where every value came from.
CREATE TABLE profiles (
    business_id  uuid NOT NULL,
    customer_id  uuid NOT NULL,
    facts        jsonb NOT NULL DEFAULT '{}',
    insights     jsonb NOT NULL DEFAULT '{}',
    provenance   jsonb NOT NULL DEFAULT '{}',
    model        text,                          -- NULL when no model was needed
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (business_id, customer_id),
    FOREIGN KEY (business_id, customer_id) REFERENCES customers (business_id, id)
);

-- ---- rules, actions, approvals ---------------------------------------------------
CREATE TABLE rules (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id  uuid NOT NULL REFERENCES businesses (id),
    name         text NOT NULL,
    source_text  text NOT NULL,                 -- the owner's own words
    compiled     jsonb NOT NULL,                -- what code checks, and code's own description of it
    active       boolean NOT NULL DEFAULT false,  -- enforced only once the owner confirms
    confirmed_by text,
    confirmed_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (business_id, id),
    CONSTRAINT rules_active_needs_confirmation CHECK (NOT active OR confirmed_at IS NOT NULL)
);

CREATE TABLE actions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id  uuid NOT NULL,
    customer_id  uuid NOT NULL,
    kind         text NOT NULL,                 -- send_message, offer, task_for_owner, ...
    payload      jsonb NOT NULL DEFAULT '{}',
    why          text,                          -- "why this, why now"
    evidence     jsonb NOT NULL DEFAULT '[]',   -- the profile facts and quotes behind `why`, checked in code
    mode         text CHECK (mode IN ('suggest', 'ask_owner', 'act_alone')),  -- autonomy dial when decided
    rule_check   jsonb,                         -- result of the code check, rule by rule
    status       text NOT NULL DEFAULT 'proposed' CHECK (status IN
                     ('proposed', 'blocked', 'suggested', 'awaiting_approval', 'approved', 'rejected', 'executed',
                      'failed')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    executed_at  timestamptz,
    UNIQUE (business_id, id),
    FOREIGN KEY (business_id, customer_id) REFERENCES customers (business_id, id)
);

CREATE TABLE approvals (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id   uuid NOT NULL,
    action_id     uuid NOT NULL,
    decision      text NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending', 'approved', 'rejected')),
    decided_by    text,
    note          text,
    requested_at  timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz,
    UNIQUE (business_id, action_id),            -- one approval per action
    FOREIGN KEY (business_id, action_id) REFERENCES actions (business_id, id)
);

-- Per-business switches, e.g. private_mode = {"guard": true, "decide": false}.
CREATE TABLE business_settings (
    business_id  uuid NOT NULL REFERENCES businesses (id),
    key          text NOT NULL,
    value        jsonb NOT NULL,
    updated_by   text NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (business_id, key)
);

-- The autonomy dial, per action type. No row means the default in pheri/autonomy.py.
CREATE TABLE autonomy (
    business_id  uuid NOT NULL REFERENCES businesses (id),
    action_kind  text NOT NULL,
    mode         text NOT NULL CHECK (mode IN ('suggest', 'ask_owner', 'act_alone')),
    updated_by   text NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (business_id, action_kind)
);

-- ---- append-only audit log -------------------------------------------------------
CREATE TABLE audit_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    business_id   uuid NOT NULL REFERENCES businesses (id),
    at            timestamptz NOT NULL DEFAULT now(),
    actor         text NOT NULL,                -- pheri, owner:<name>, system
    event         text NOT NULL,                -- decided, rule_blocked, approved, sent, ...
    subject_type  text,
    subject_id    text,
    details       jsonb NOT NULL DEFAULT '{}'
);

CREATE FUNCTION audit_log_is_append_only() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
END $$;

CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_is_append_only();

-- ---- spend ledger ----------------------------------------------------------------
-- Global, not per tenant: the free-credit cap covers every business at once.
-- Columns match pheri/ledger.py exactly.
CREATE TABLE spend_ledger (
    id             text PRIMARY KEY,
    created_at     double precision NOT NULL,
    provider       text NOT NULL,
    model          text NOT NULL,
    purpose        text NOT NULL,
    status         text NOT NULL CHECK (status IN ('reserved', 'settled', 'released')),
    estimate_usd   double precision NOT NULL,
    actual_usd     double precision,
    input_tokens   integer,
    cached_tokens  integer,
    output_tokens  integer,
    gpu_seconds    double precision
);

-- ---- row-level security ----------------------------------------------------------
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE businesses FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON businesses
    USING (id = app_business_id()) WITH CHECK (id = app_business_id());

ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON customers
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON events
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON messages
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON profiles
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE rules FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rules
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE actions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON actions
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON approvals
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE autonomy ENABLE ROW LEVEL SECURITY;
ALTER TABLE autonomy FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON autonomy
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE business_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_settings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON business_settings
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON audit_log
    USING (business_id = app_business_id()) WITH CHECK (business_id = app_business_id());

-- ---- grants: least privilege for the app -----------------------------------------
DO $$
BEGIN
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO pheri_app', current_schema());
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO pheri_app', current_schema());
END $$;

GRANT EXECUTE ON FUNCTION app_business_id() TO pheri_app;
GRANT SELECT ON businesses TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON customers TO pheri_app;
GRANT SELECT, INSERT ON events TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON messages TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON profiles TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON rules TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON actions TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON approvals TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON autonomy TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON business_settings TO pheri_app;
GRANT SELECT, INSERT ON audit_log TO pheri_app;
GRANT SELECT, INSERT, UPDATE ON spend_ledger TO pheri_app;

COMMIT;
