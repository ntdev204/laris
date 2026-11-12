"""PostgreSQL tests run only when LARIS_TEST_PG_DSN points at a disposable database; each test
works in its own schema, which is dropped afterwards."""

import os
import uuid

import pytest

DSN = os.environ.get("LARIS_TEST_PG_DSN", "")


@pytest.fixture
def pg():
    if not DSN:
        pytest.skip("LARIS_TEST_PG_DSN is not set")
    from laris.server.storage import PgDatabase

    schema = "t_" + uuid.uuid4().hex[:10]
    db = PgDatabase(DSN, schema=schema, max_size=12)
    yield db
    db.session().execute(f'DROP SCHEMA "{schema}" CASCADE')
    db.close()
