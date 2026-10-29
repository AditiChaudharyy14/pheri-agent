"""db/schema.sql. The static checks always run; the real-Postgres checks need PHERI_TEST_DATABASE_URL."""

import re

import pytest

from pheri.config import REPO_ROOT, Settings
from pheri.ledger import _SCHEMA_SQLITE
from pheri.synth import BUSINESS_IDS

from conftest import throwaway_schema

SQL = (REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
TABLES = re.findall(r"^CREATE TABLE (\w+) \(", SQL, re.M)
GLOBAL_TABLES = {"spend_ledger"}  # the spend cap covers every business at once
TENANT_TABLES = [t for t in TABLES if t not in GLOBAL_TABLES]
BD, KC = BUSINESS_IDS["brightdesk"], BUSINESS_IDS["birgunj"]


def _columns(sql: str, table: str) -> list[str]:
    body = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{table} \((.*?)\n\);", sql, re.S).group(1)
    lines = [ln.split("--")[0].strip() for ln in body.splitlines()]
    return [ln.split()[0] for ln in lines if ln and not ln.startswith(("PRIMARY", "UNIQUE", "FOREIGN"))]


# ---- static -------------------------------------------------------------------------
def test_all_tables_exist():
    assert set(TABLES) == {"businesses", "customers", "events", "messages", "profiles", "rules", "actions",
                           "approvals", "autonomy", "business_settings", "audit_log", "spend_ledger"}


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_tenant_table_has_forced_rls_and_a_policy(table):
    key = "id" if table == "businesses" else "business_id"
    assert key == "id" or "business_id" in _columns(SQL, table)
    assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in SQL
    assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in SQL
    assert re.search(rf"CREATE POLICY \w+ ON {table}\s+USING \({key} = app_business_id\(\)\) "
                     rf"WITH CHECK \({key} = app_business_id\(\)\);", SQL)


def test_tenant_comes_from_the_session_setting_and_fails_closed():
    assert "NULLIF(current_setting('app.business_id', true), '')::uuid" in SQL


def test_app_role_is_least_privilege():
    assert "CREATE ROLE pheri_app NOLOGIN NOBYPASSRLS;" in SQL
    assert "GRANT ALL" not in SQL.upper()
    assert re.findall(r"GRANT ([A-Z, ]+) ON audit_log TO pheri_app;", SQL) == ["SELECT, INSERT"]
    assert re.findall(r"GRANT ([A-Z, ]+) ON businesses TO pheri_app;", SQL) == ["SELECT"]


def test_audit_log_triggers_block_rewrites():
    assert "BEFORE UPDATE OR DELETE ON audit_log\n    FOR EACH ROW" in SQL
    assert "BEFORE TRUNCATE ON audit_log\n    FOR EACH STATEMENT" in SQL


def test_spend_ledger_matches_ledger_py():
    assert _columns(SQL, "spend_ledger") == _columns(_SCHEMA_SQLITE, "spend_ledger")


def test_seeded_business_ids_match_synth():
    for slug, bid in BUSINESS_IDS.items():
        assert f"('{bid}', '{slug}'," in SQL


# ---- real Postgres --------------------------------------------------------------------
# Neon's pooled endpoint (PgBouncer, transaction mode) hands one server session to many clients,
# so a session-level SET ROLE or set_config(..., false) leaks into whoever gets that session next.
# Every step below is one transaction with only LOCAL settings: the same rule the app must follow.
URL = Settings().test_database_url
needs_pg = pytest.mark.skipif(
    not URL, reason="PHERI_TEST_DATABASE_URL not set: real-Postgres RLS tests skipped (static checks still ran)")


def _tx(pg, sql, params=None, *, role="pheri_app", business=None):
    """Run one statement in its own transaction. role=None means the session user (the owner)."""
    psycopg, schema = pg
    with psycopg.connect(URL) as con:  # not autocommit: the block commits, or rolls back on error
        con.execute(f'SET LOCAL search_path TO "{schema}"')
        con.execute(f"SET LOCAL ROLE {role}" if role else "SET LOCAL ROLE NONE")
        con.execute("SET LOCAL app.business_id TO DEFAULT")  # ignore anything a pooled session carried over
        if business is not None:
            con.execute("SELECT set_config('app.business_id', %s, true)", (business,))
        cur = con.execute(sql, params)
        return cur.fetchall() if cur.description else None


@pytest.fixture(scope="module")
def pg():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(URL) as con:
        con.execute("SET LOCAL ROLE NONE")
        for (old,) in con.execute(r"SELECT nspname FROM pg_namespace WHERE nspname LIKE 'pheri\_test\_%'").fetchall():
            con.execute(f'DROP SCHEMA "{old}" CASCADE')  # left behind by an aborted earlier run
    with throwaway_schema() as pg:
        yield pg


def _emails(pg, business=None):
    return sorted(r[0] for r in _tx(pg, "SELECT email FROM customers", business=business))


def _add_customer(pg, business, email, as_business=None):
    _tx(pg, "INSERT INTO customers (business_id, email) VALUES (%s, %s)", (business, email),
        business=as_business or business)


@needs_pg
def test_tenants_only_see_their_own_rows(pg):
    _add_customer(pg, BD, "iso-a@x.example")
    _add_customer(pg, KC, "iso-b@x.example")
    assert "iso-a@x.example" in _emails(pg, BD) and "iso-b@x.example" not in _emails(pg, BD)
    assert "iso-b@x.example" in _emails(pg, KC) and "iso-a@x.example" not in _emails(pg, KC)
    assert _tx(pg, "SELECT slug FROM businesses", business=BD) == [("brightdesk",)]


@needs_pg
def test_cannot_write_into_another_tenant(pg):
    psycopg, _ = pg
    with pytest.raises(psycopg.Error, match="row-level security"):
        _add_customer(pg, KC, "sneak@x.example", as_business=BD)
    _add_customer(pg, BD, "move@x.example")
    with pytest.raises(psycopg.Error, match="row-level security"):
        _tx(pg, "UPDATE customers SET business_id = %s WHERE email = 'move@x.example'", (KC,), business=BD)


@needs_pg
def test_no_tenant_set_means_no_rows(pg):
    _add_customer(pg, BD, "closed@x.example")
    assert _emails(pg) == []
    assert _emails(pg, business="") == []


@needs_pg
def test_tenant_setting_never_outlives_its_transaction(pg):
    psycopg, schema = pg
    _add_customer(pg, BD, "scoped@x.example")
    with psycopg.connect(URL, autocommit=True) as con:
        for business, expected in ((BD, True), (None, False)):
            with con.transaction():
                con.execute(f'SET LOCAL search_path TO "{schema}"')
                con.execute("SET LOCAL ROLE pheri_app")
                if business:
                    con.execute("SELECT set_config('app.business_id', %s, true)", (business,))
                seen = con.execute("SELECT count(*) FROM customers").fetchone()[0]
                assert (seen > 0) is expected


@needs_pg
def test_app_role_is_not_owner_and_cannot_bypass_rls(pg):
    _, schema = pg
    assert _tx(pg, "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'pheri_app'", role=None) \
        == [(False, False)]
    owners = {r[0] for r in _tx(pg, "SELECT tableowner FROM pg_tables WHERE schemaname = %s", (schema,), role=None)}
    assert owners and "pheri_app" not in owners


@needs_pg
def test_audit_log_is_append_only(pg):
    psycopg, _ = pg
    _tx(pg, "INSERT INTO audit_log (business_id, actor, event) VALUES (%s, 'pheri', 'test')", (BD,), business=BD)
    for sql in ("UPDATE audit_log SET event = 'edited'", "DELETE FROM audit_log"):
        with pytest.raises(psycopg.Error, match="permission denied"):  # the app role has no grant
            _tx(pg, sql, business=BD)
    # The owner has the grants (and on Neon even BYPASSRLS), and the trigger still stops it.
    for sql in ("UPDATE audit_log SET event = 'edited'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        with pytest.raises(psycopg.Error, match="append-only"):
            _tx(pg, sql, role=None, business=BD)
    assert _tx(pg, "SELECT event FROM audit_log", business=BD) == [("test",)]
