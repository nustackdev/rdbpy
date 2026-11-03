"""Lifetime of iterators, snapshots and transactions relative to their parent.

A use-after-free here crashes the interpreter, so every scenario runs in its
own subprocess with freed memory poisoned (PYTHONMALLOC=debug for Python
objects, MALLOC_PERTURB_ / MallocScribble for native ones). A test passes
only if the child exits cleanly and printed the expected markers.
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
import threading

import rdbpy

TMP = tempfile.mkdtemp()
_n = [0]


def path():
    _n[0] += 1
    return os.path.join(TMP, "db%d" % _n[0])


def txndb(p=None):
    return rdbpy.TransactionDB(p or path(), lock_timeout_ms=100)


def plaindb(p=None):
    return rdbpy.DB(p or path())


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
    env["PYTHONMALLOC"] = "debug"
    env["MALLOC_PERTURB_"] = "165"
    env["MallocScribble"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in [os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src",
                    env.get("PYTHONPATH", "")] if p
    )
    code = PRELUDE + textwrap.dedent(body) + "\nprint('DONE')\n"
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    out = proc.stdout.splitlines()
    for marker in expected:
        assert marker in out, f"missing {marker!r} in {out}"
    assert "DONE" in out


@pytest.mark.parametrize("end", ["commit", "rollback"])
def test_txn_iterator_invalid_after_txn_ends(end):
    run(
        f"""
        db = txndb()
        fill(db)
        txn = db.begin()
        it = txn.iterator()
        it.seek_to_first()
        txn.{end}()
        raises(it.valid)
        raises(lambda: it.next_batch(10))
        del it
        gc.collect()
        db.close()
        """,
        "RAISED RuntimeError",
    )


def test_db_close_frees_children_then_objects():
    run(
        """
        db = txndb()
        fill(db)
        it = db.iterator()
        it.seek_to_first()
        snap = db.snapshot()
        txn = db.begin()
        txn.put(b"x", b"1")
        tit = txn.iterator()
        db.close()
        raises(it.valid)
        raises(lambda: db.get(b"k000000", snapshot=snap))
        raises(lambda: txn.get(b"x"))
        raises(tit.valid)
        print("ACTIVE", txn.active, snap.released, it.closed)
        del it, snap, txn, tit
        gc.collect()
        del db
        gc.collect()
        """,
        "RAISED RuntimeError",
        "ACTIVE False True True",
    )


def test_children_outlive_db_reference():
    run(
        """
        db = plaindb()
        fill(db)
        it = db.iterator()
        it.seek_to_first()
        snap = db.snapshot()
        del db
        gc.collect()
        print("STILL", it.valid(), snap.sequence > 0)
        del it
        gc.collect()
        del snap
        gc.collect()
        """,
        "STILL True True",
    )


def test_txn_outlives_db_reference_and_commits():
    run(
        """
        p = path()
        db = txndb(p)
        txn = db.begin()
        txn.put(b"a", b"1")
        del db
        gc.collect()
        txn.commit()
        del txn
        gc.collect()
        with plaindb(p) as check:
            print("VALUE", check.get(b"a"))
        """,
        "VALUE b'1'",
    )


def test_gc_frees_live_txn_and_iterator_in_any_order():
    run(
        """
        db = txndb()
        fill(db)
        txn = db.begin()
        txn.put(b"a", b"1")
        its = [txn.iterator() for _ in range(5)]
        for it in its:
            it.seek_to_first()
        del its[2]
        del txn
        gc.collect()
        print("IT", its[0].closed)
        del its
        gc.collect()
        db.close()
        """,
        "IT True",
    )


def test_many_iterators_random_order():
    run(
        """
        import random
        db = txndb()
        fill(db)
        txn = db.begin()
        objs = [db.iterator() for _ in range(50)] + [txn.iterator() for _ in range(50)]
        objs += [db.snapshot() for _ in range(20)]
        random.seed(7)
        random.shuffle(objs)
        for o in objs[:60]:
            if isinstance(o, rdbpy.Iterator):
                o.seek_to_first()
        del objs[:60]
        gc.collect()
        txn.rollback()
        del objs
        gc.collect()
        db.close()
        """,
    )


def test_generator_finally_rolls_back_during_gc():
    run(
        """
        db = txndb()
        fill(db)

        def scan():
            txn = db.begin()
            it = txn.iterator()
            try:
                for row in it:
                    yield row
            finally:
                txn.rollback()

        g = scan()
        next(g)
        del g  # generator finalizer ends the txn while its iterator is live
        gc.collect()
        db.close()
        """,
    )


def test_close_while_other_thread_collects():
    run(
        """
        db = txndb()
        fill(db)
        stop = threading.Event()

        def churn():
            while not stop.is_set():
                gc.collect()

        t = threading.Thread(target=churn)
        t.start()
        for _ in range(200):
            txn = db.begin()
            it = txn.iterator()
            it.seek_to_first()
            del txn, it
        db.close()
        stop.set()
        t.join()
        """,
    )


def test_snapshot_after_txn_ends_and_db_closes():
    run(
        """
        db = txndb()
        txn = db.begin(set_snapshot=True)
        view = txn.snapshot
        txn.commit()
        print("VIEW", view.released)
        owned = db.snapshot()
        db.close()
        print("OWNED", owned.released)
        del view, owned
        gc.collect()
        """,
        "VIEW True",
        "OWNED True",
    )



def test_close_refused_while_another_thread_is_inside_a_call():
    # Closing would free the txn another thread is blocked in (a crash before).
    run(
        """
        import time
        db = rdbpy.TransactionDB(path(), lock_timeout_ms=2000)
        holder = db.begin()
        holder.put(b"k", b"1")
        waiter = db.begin()
        out = []
        th = threading.Thread(target=lambda: out.append(waiter.get_for_update(b"k")))
        th.start()
        time.sleep(0.2)
        raises(db.close)
        holder.rollback()
        th.join()
        print("GOT", out)
        db.close()
        raises(lambda: waiter.get(b"k"))
        """,
        "RAISED RuntimeError",
        "GOT [None]",
    )
