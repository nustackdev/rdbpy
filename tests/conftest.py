"""Shared fixtures: fresh databases in a temporary directory."""

import pytest

import rdbpy


@pytest.fixture
def path(tmp_path):
    n = [0]

    def make():
        n[0] += 1
        return str(tmp_path / f"db{n[0]}")

    return make


@pytest.fixture
def db(path):
    d = rdbpy.DB(path(), rdbpy.Options(create_if_missing=True))
    yield d
    d.close()


@pytest.fixture
def tdb(path):
    d = rdbpy.TransactionDB(
        path(), rdbpy.Options(create_if_missing=True), lock_timeout_ms=200, default_lock_timeout_ms=200
    )
    yield d
    d.close()


@pytest.fixture
def odb(path):
    d = rdbpy.OptimisticTransactionDB(path(), rdbpy.Options(create_if_missing=True))
    yield d
    d.close()


def fill(db, n=100, prefix=b"k"):
    for i in range(n):
        db.put(prefix + b"%04d" % i, b"v%04d" % i)
