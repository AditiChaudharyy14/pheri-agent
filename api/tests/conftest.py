import re
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pheri.config import REPO_ROOT, Settings  # noqa: E402

PG_URL = Settings().test_database_url


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
