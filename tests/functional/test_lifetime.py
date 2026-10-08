"""Lifetime of iterators, snapshots and transactions relative to their parent.

A use-after-free here crashes the interpreter, so every scenario runs in its
own subprocess with freed memory poisoned: PYTHONMALLOC=debug for Python
objects, MallocScribble (macOS) and MALLOC_PERTURB_ (glibc) for native ones.
A test passes only if the child exits cleanly and printed the expected
markers.

Several scenarios force gc to run inside rdbpy calls (via gc thresholds,
which bite on CPython <= 3.11, or a gc thread, which bites on any version).
"""

import os
import subprocess
import sys
import textwrap

import pytest


PRELUDE = """
import gc
import os
import tempfile

import rdbpy

TMP = tempfile.mkdtemp()
_n = [0]


def path():
    _n[0] += 1
    return os.path.join(TMP, "db%d" % _n[0])


def txndb(p=None):
    return rdbpy.TransactionDB(p or path(), rdbpy.Options(create_if_missing=True))


def plaindb(p=None):
    return rdbpy.DB(p or path(), rdbpy.Options(create_if_missing=True))


def fill(db, n=2000):
    for i in range(n):
        db.put(b"k%06d" % i, b"v" * 64)
    db.flush()


def raises(fn, exc=RuntimeError):
    try:
        fn()
    except exc as e:
        print("RAISED", type(e).__name__)
        return
    print("NO RAISE")
"""


def run(body: str, *expected: str) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env["PYTHONMALLOC"] = "debug"
    env["MallocScribble"] = "1"
    env["MALLOC_PERTURB_"] = "85"
    code = PRELUDE + textwrap.dedent(body) + '\nprint("DONE")\n'
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"child exited with {proc.returncode}:\n{out}"
    assert "NO RAISE" not in out, out
    for marker in (*expected, "DONE"):
        assert marker in out, f"missing {marker!r}:\n{out}"


@pytest.mark.parametrize("end", ["commit", "rollback", "close"])
def test_txn_iterator_invalid_after_txn_ends(end: str) -> None:
    run(
        f"""
        db = txndb()
        fill(db)
        txn = db.begin_transaction()
        txn.put(b"a", b"1")
        it = txn.iteritems()
        it.seek_to_first()
        it.get()
        txn.{end}()
        raises(it.seek_to_first)
        raises(it.get)
        raises(it.next)
        raises(it.skip)
        raises(it.skip_back)
        raises(lambda: it.seek(b"k"))
        raises(lambda: it.seek_for_prev(b"k"))
        raises(it.seek_to_last)
        del it
        gc.collect()
        """,
        "RAISED RuntimeError",
    )


def test_txn_iterator_invalid_after_rollback_to_save_point() -> None:
    run(
        """
        db = txndb()
        txn = db.begin_transaction()
        txn.save_point()
        for i in range(5000):
            txn.put(b"t%06d" % i, b"x" * 64)
        it = txn.iteritems()
        it.seek_to_first()
        txn.rollback_to_save_point()
        raises(it.get)
        txn.commit()
        """,
        "RAISED RuntimeError",
    )


def test_txn_iterator_invalid_after_reuse() -> None:
    run(
        """
        db = txndb()
        txn = db.begin_transaction()
        for i in range(5000):
            txn.put(b"t%06d" % i, b"x" * 64)
        it = txn.iterkeys()
        it.seek_to_first()
        db.begin_transaction(reuse=txn)
        raises(it.get)
        txn.rollback()
        """,
        "RAISED RuntimeError",
    )


def test_reversed_iterator_invalid_after_commit() -> None:
    run(
        """
        db = txndb()
        fill(db)
        txn = db.begin_transaction()
        rit = reversed(txn.iterkeys())
        rit.seek_to_last()
        txn.commit()
        raises(lambda: next(rit))
        """,
        "RAISED RuntimeError",
    )


def test_db_iterator_across_db_close() -> None:
    run(
        """
        db = plaindb()
        fill(db)
        it = db.iteritems()
        it.seek_to_first()
        dropped = db.iterkeys()
        dropped.seek_to_first()
        db.close()
        del dropped
        gc.collect()
        raises(it.get)
        del it
        del db
        gc.collect()
        """,
        "RAISED RuntimeError",
    )


def test_plain_db_close_then_free() -> None:
    run(
        """
        db = plaindb()
        db.put(b"a", b"1")
        db.close()
        db.close()
        del db
        gc.collect()
        print("FREED")
        """,
        "FREED",
    )


@pytest.mark.parametrize("kind", ["plaindb", "txndb"])
def test_db_methods_after_close_raise(kind: str) -> None:
    run(
        f"""
        db = {kind}()
        db.put(b"a", b"1")
        db.close()
        raises(lambda: db.get(b"a"))
        raises(lambda: db.put(b"a", b"2"))
        raises(lambda: db.iterkeys())
        raises(lambda: db.iteritems())
        raises(lambda: db.snapshot())
        raises(lambda: db.write(rdbpy.WriteBatch()))
        raises(lambda: db.get_property(b"rocksdb.stats"))
        """,
        "RAISED RuntimeError",
    )


def test_live_txn_and_iterator_across_txndb_close() -> None:
    run(
        """
        p = path()
        db = txndb(p)
        fill(db)
        txn = db.begin_transaction()
        txn.put(b"uncommitted", b"1")
        it = txn.iterkeys()
        it.seek_to_first()
        db.close()
        raises(lambda: txn.put(b"b", b"2"))
        raises(txn.commit)
        raises(it.get)
        txn.rollback()
        txn.close()
        del it, txn, db
        gc.collect()
        db = txndb(p)
        print("VISIBLE", db.get(b"uncommitted"))
        """,
        "RAISED RuntimeError",
        "VISIBLE None",
    )


def test_snapshot_across_db_close() -> None:
    run(
        """
        db = plaindb()
        db.put(b"a", b"1")
        snap = db.snapshot()
        db.close()
        del snap
        gc.collect()
        print("FREED")
        """,
        "FREED",
    )


def test_iterator_only_reachable_from_garbage_traceback() -> None:
    # gc may clear the iterator before the frame that owns it; the iterator
    # must still free its native state before its transaction and DB go.
    run(
        """
        class Store:
            def __init__(self, p):
                self.db = txndb(p)
                fill(self.db)

        def scan_then_fail(store):
            txn = store.db.begin_transaction()
            it = txn.iterkeys()
            it.seek_to_first()
            store.self_ref = store
            raise AttributeError("boom")

        for _ in range(20):
            try:
                scan_then_fail(Store(path()))
            except AttributeError as e:
                err = e
                err.self_ref = err
            del err
            gc.collect()
        """,
    )


def test_generator_finally_commits_during_gc() -> None:
    # The commit runs from gc's finalizer phase, after weakrefs to garbage are
    # cleared; the still-alive iterator must be invalidated anyway.
    run(
        """
        class Store:
            def __init__(self, p):
                self.db = txndb(p)
                fill(self.db)

        def scan(store):
            txn = store.db.begin_transaction()
            it = txn.iterkeys()
            it.seek_to_first()
            try:
                while True:
                    yield it.next()
            finally:
                txn.commit()
                raises(it.get)

        for _ in range(20):
            store = Store(path())
            g = scan(store)
            next(g)
            store.g = g
            del store, g
            gc.collect()
        """,
        "RAISED RuntimeError",
    )


def test_close_while_gc_frees_other_transactions() -> None:
    # Live transactions with iterators plus garbage transactions in cycles.
    # Releasing the live ones during close() must not let gc (triggered by an
    # allocation at a chosen point) free a garbage transaction that close()
    # still has queued.
    run(
        """
        for extra in range(10):
            db = txndb()
            db.put(b"a", b"1")
            keep = []
            for i in range(30):
                t = db.begin_transaction()
                keep.append((t, t.iterkeys()))
            gc.disable()
            gc.collect()
            for i in range(30):
                t = db.begin_transaction()
                cyc = [t]
                cyc.append(cyc)
                del cyc, t
            gc.set_threshold(gc.get_count()[0] + extra, 10, 10)
            gc.enable()
            db.close()
            gc.set_threshold(700, 10, 10)
            del keep, db
            gc.collect()
        """,
    )


def test_close_while_other_thread_collects() -> None:
    # gc can run on any thread, even one that never touches the DB.
    run(
        """
        import threading

        stop = []

        def collector():
            while not stop:
                gc.collect(0)

        threading.Thread(target=collector, daemon=True).start()
        for rnd in range(10):
            db = txndb()
            live = []
            for i in range(20):
                t = db.begin_transaction()
                t.put(b"k%d" % i, b"v")
                live.append((t, t.iterkeys()))
            for i in range(40):
                t = db.begin_transaction()
                t.put(b"g%d" % i, b"v")
                cyc = [t]
                cyc.append(cyc)
                del cyc, t
            snap = db.snapshot()
            db.close()
            del live, db, snap
        stop.append(1)
        """,
    )


@pytest.mark.parametrize("end", ["commit", "close"])
def test_finalizer_ends_txn_during_commit_or_close(end: str) -> None:
    # A garbage scan generator whose finally rolls back the transaction runs
    # from gc while commit()/close() are mid-way through the same transaction.
    run(
        f"""
        def scan(t):
            it = t.iterkeys()
            it.seek_to_first()
            try:
                while True:
                    yield it.next()
            finally:
                t.rollback()

        for extra in range(7):
            db = txndb()
            db.put(b"a", b"1")
            txn = db.begin_transaction()
            txn.put(b"b", b"2")
            gc.disable()
            gc.collect()
            g = scan(txn)
            next(g)
            cyc = [g]
            cyc.append(cyc)
            del g, cyc
            gc.set_threshold(gc.get_count()[0] + extra, 10, 10)
            gc.enable()
            if "{end}" == "close":
                db.close()
            else:
                try:
                    txn.commit()
                except RuntimeError:
                    pass
            gc.set_threshold(700, 10, 10)
            del txn, db
            gc.collect()
        """,
    )


@pytest.mark.parametrize("kind", ["db", "txn"])
def test_multi_get_keys_iterable_closes_db(kind: str) -> None:
    run(
        f"""
        db = txndb() if "{kind}" == "txn" else plaindb()
        target = db.begin_transaction() if "{kind}" == "txn" else db

        class Keys:
            def __len__(self):
                return 2

            def __getitem__(self, i):
                return [b"a", b"b"][i]

            def __iter__(self):
                yield b"a"
                db.close()
                yield b"b"

        raises(lambda: target.multi_get(Keys()))
        """,
        "RAISED RuntimeError",
    )


def test_bare_iterator_raises() -> None:
    run(
        """
        db = plaindb()
        raises(lambda: rdbpy.KeysIterator(db).next())
        """,
        "RAISED RuntimeError",
    )


def test_many_iterators_random_order() -> None:
    run(
        """
        import random

        db = txndb()
        fill(db)
        rnd = random.Random(0)
        for _ in range(200):
            txn = db.begin_transaction()
            its = [rnd.choice([txn.iterkeys, txn.iteritems, db.iterkeys])() for _ in range(5)]
            for it in its:
                it.seek_to_first()
            rnd.shuffle(its)
            del its[:2]
            rnd.choice([txn.commit, txn.rollback])()
            del its, txn
        live = db.iterkeys()
        live.seek_to_first()
        db.close()
        del live
        gc.collect()
        """,
    )
