import re
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from pheri.config import REPO_ROOT, Settings  # noqa: E402
from pheri.store import MemoryStore, PgStore  # noqa: E402
from pheri.synth import BUSINESS_IDS  # noqa: E402

PG_URL = Settings().test_database_url
# Postgres round trips are slow from here (up to ~0.8 s each), so the real-database run covers the
# flows where the backend matters; mark those tests with BOTH to run them on memory and Postgres.
BOTH = pytest.mark.parametrize("store", ["memory", "pg"], indirect=True)
TENANT_TABLES_TO_CLEAR = ("approvals", "actions", "autonomy", "rules", "business_settings", "customers")


@contextmanager
def throwaway_schema():
    """db/schema.sql loaded into a fresh schema on the test database, dropped afterwards."""
    import psycopg

    sql = (REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    schema = f"pheri_test_{uuid.uuid4().hex[:8]}"
    body = re.sub(r"^(BEGIN|COMMIT);$", "", sql, flags=re.M)  # we hold the transaction ourselves
    with psycopg.connect(PG_URL) as con:
        con.execute("SET LOCAL ROLE NONE")
        con.execute(f'CREATE SCHEMA "{schema}"')
        con.execute(f'SET LOCAL search_path TO "{schema}"')
        con.execute(body)
        con.execute("GRANT pheri_app TO CURRENT_USER")  # so the tests can SET LOCAL ROLE pheri_app
    try:
        yield psycopg, schema
    finally:
        with psycopg.connect(PG_URL) as con:
            con.execute("SET LOCAL ROLE NONE")
            con.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture(scope="module")
def pg_schema():
    if not PG_URL:
        pytest.skip("PHERI_TEST_DATABASE_URL not set: Postgres store tests skipped (memory store still ran)")
    pytest.importorskip("psycopg")
    with throwaway_schema() as pg:
        yield pg


@pytest.fixture
def store(request):
    """The memory store; tests marked with BOTH also run on real Postgres."""
    if getattr(request, "param", "memory") == "memory":
        yield MemoryStore("brightdesk")
        return
    psycopg, schema = request.getfixturevalue("pg_schema")
    # One schema per module (creating one takes seconds on Neon); each test starts with empty tables.
    # The audit log is append-only even here, so tests read it by subject id.
    with psycopg.connect(PG_URL) as con:
        con.execute(f'SET LOCAL search_path TO "{schema}"')
        con.execute("SELECT set_config('app.business_id', %s, true)", (BUSINESS_IDS["brightdesk"],))
        for table in TENANT_TABLES_TO_CLEAR:
            con.execute(f"DELETE FROM {table}")
    pg_store = PgStore("brightdesk", PG_URL, schema=schema)
    yield pg_store
    pg_store.close()
