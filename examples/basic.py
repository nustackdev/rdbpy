"""Basic rdbpy example: open, put/get, iterate, transact.

Run:
    python examples/basic.py

Uses a temp directory so it cleans up after itself.
"""

import shutil
import tempfile
from pathlib import Path

import rdbpy


def open_put_get(path: Path) -> None:
    db = rdbpy.DB(str(path), rdbpy.Options(create_if_missing=True))

    db.put(b"user:1", b"ada")
    db.put(b"user:2", b"grace")
    db.put(b"user:3", b"hedy")

    assert db.get(b"user:1") == b"ada"
    assert db.get(b"missing") is None

    print("put/get     ok")

    # Iterate keys in order.
    it = db.iterkeys()
    it.seek_to_first()
    keys = list(it)
    assert keys == [b"user:1", b"user:2", b"user:3"], keys
    print("iterkeys    ok ->", keys)

    # Delete one.
    db.delete(b"user:2")
    assert db.get(b"user:2") is None
    print("delete      ok")

    del db


def transactional(path: Path) -> None:
    opts = rdbpy.Options(create_if_missing=True)
    db = rdbpy.TransactionDB(str(path), opts, txn_db_opts=rdbpy.TransactionDBOptions())

    # Commit: writes persist.
    txn = db.begin_transaction()
    txn.put(b"a", b"1")
    txn.put(b"b", b"2")
    txn.commit()
    txn.close()
    assert db.get(b"a") == b"1"
    assert db.get(b"b") == b"2"
    print("commit      ok")

    # Rollback: writes discarded.
    txn = db.begin_transaction()
    txn.put(b"c", b"3")
    txn.rollback()
    txn.close()
    assert db.get(b"c") is None
    print("rollback    ok")

    del db


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="rdbpy-example-"))
    try:
        open_put_get(root / "kv")
        transactional(root / "txn")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\nall good.")


if __name__ == "__main__":
    main()
