"""The GIL is released inside blocking RocksDB calls: a thread stuck in a lock
wait must not stop other Python threads."""

import threading
import time

import pytest

import rdbpy


def test_lock_wait_does_not_block_other_threads(tdb):
    tdb.put(b"a", b"1")
    holder = tdb.begin()
    holder.get_for_update(b"a")
    waiter = tdb.begin(lock_timeout_ms=1500)
    started = threading.Event()
    result = []

    def wait_on_lock():
        started.set()
        try:
            waiter.get_for_update(b"a")
            result.append("ok")
        except rdbpy.TimedOut:
            result.append("timeout")

    th = threading.Thread(target=wait_on_lock)
    th.start()
    started.wait()
    time.sleep(0.05)
    assert th.is_alive()
    # Main thread makes progress, including its own rocksdb calls, while the
    # waiter sits inside GetForUpdate.
    t0 = time.monotonic()
    n = 0
    while time.monotonic() - t0 < 0.5:
        assert tdb.get(b"a") == b"1"
        n += 1
    assert n > 100
    assert th.is_alive()
    holder.rollback()
    th.join(timeout=3)
    assert result == ["ok"]
    waiter.rollback()


def test_parallel_readers_overlap(db):
    for i in range(2000):
        db.put(b"k%05d" % i, b"x" * 200)
    db.flush()
    barrier = threading.Barrier(4)
    counts = []

    def reader():
        barrier.wait()
        n = 0
        t0 = time.monotonic()
        while time.monotonic() - t0 < 0.3:
            for row in db.iterator().next_batch(500):
                n += 1
        counts.append(n)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(counts) == 4
    assert all(c > 0 for c in counts)


def test_concurrent_writers_on_txn_db(tdb):
    tdb.put(b"n", b"0")
    errors = []

    def inc():
        for _ in range(20):
            while True:
                txn = tdb.begin(lock_timeout_ms=2000)
                try:
                    v = int(txn.get_for_update(b"n"))
                    txn.put(b"n", b"%d" % (v + 1))
                    txn.commit()
                    break
                except (rdbpy.Busy, rdbpy.TimedOut):
                    txn.rollback()
                except Exception as e:  # pragma: no cover
                    errors.append(e)
                    txn.rollback()
                    break

    threads = [threading.Thread(target=inc) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert tdb.get(b"n") == b"80"


def test_optimistic_retry_loop(odb):
    odb.put(b"n", b"0")
    attempts = [0]

    def inc():
        for _ in range(20):
            while True:
                txn = odb.begin()
                attempts[0] += 1
                v = int(txn.get_for_update(b"n"))
                txn.put(b"n", b"%d" % (v + 1))
                try:
                    txn.commit()
                    break
                except rdbpy.Busy:
                    pass

    threads = [threading.Thread(target=inc) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert odb.get(b"n") == b"80"
    assert attempts[0] >= 80
