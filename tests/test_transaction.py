"""Transactions: pessimistic and optimistic semantics, conflicts, typed errors."""

import threading
import time

import pytest

import rdbpy


# ---------------------------------------------------------------------------
# basics, both flavours
# ---------------------------------------------------------------------------


@pytest.fixture(params=["pessimistic", "optimistic"])
def anydb(request, path):
    if request.param == "pessimistic":
        d = rdbpy.TransactionDB(path(), lock_timeout_ms=200)
    else:
        d = rdbpy.OptimisticTransactionDB(path())
    yield d
    d.close()


def test_read_own_writes_and_commit(anydb):
    anydb.put(b"a", b"1")
    txn = anydb.begin()
    assert txn.active
    assert txn.optimistic == isinstance(anydb, rdbpy.OptimisticTransactionDB)
    assert txn.get(b"a") == b"1"
    txn.put(b"a", b"2")
    txn.put(b"b", b"3")
    txn.delete(b"a")
    assert txn.get(b"a") is None
    assert txn.get(b"b") == b"3"
    assert anydb.get(b"b") is None  # not visible outside before commit
    assert txn.num_keys == 2
    txn.commit()
    assert txn.committed
    assert not txn.active
    assert anydb.get(b"a") is None
    assert anydb.get(b"b") == b"3"


def test_rollback_discards(anydb):
    anydb.put(b"a", b"1")
    txn = anydb.begin()
    txn.put(b"a", b"2")
    txn.rollback()
    assert not txn.active
    assert not txn.committed
    assert anydb.get(b"a") == b"1"
    txn.rollback()  # idempotent


def test_ended_txn_raises(anydb):
    txn = anydb.begin()
    txn.commit()
    for call in (
        lambda: txn.get(b"a"),
        lambda: txn.put(b"a", b"1"),
        lambda: txn.delete(b"a"),
        lambda: txn.get_for_update(b"a"),
        lambda: txn.iterator(),
        lambda: txn.set_snapshot(),
        lambda: txn.commit(),
        lambda: txn.id,
    ):
        with pytest.raises(RuntimeError):
            call()
    txn.rollback()  # no-op


def test_context_manager_rolls_back(anydb):
    with anydb.begin() as txn:
        txn.put(b"a", b"1")
    assert not txn.active
    assert anydb.get(b"a") is None
    with anydb.begin() as txn:
        txn.put(b"a", b"1")
        txn.commit()
    assert anydb.get(b"a") == b"1"
    with pytest.raises(ZeroDivisionError):
        with anydb.begin() as txn:
            txn.put(b"a", b"2")
            1 / 0
    assert anydb.get(b"a") == b"1"


def test_db_close_rolls_back_live_txn(path):
    db = rdbpy.TransactionDB(path())
    txn = db.begin()
    txn.put(b"a", b"1")
    db.close()
    assert not txn.active
    with rdbpy.DB(db.path) as plain:
        assert plain.get(b"a") is None


def test_many_sequential_txns(anydb):
    for i in range(200):
        txn = anydb.begin()
        txn.put(b"k", b"%d" % i)
        txn.commit()
    assert anydb.get(b"k") == b"199"


def test_write_options_on_begin(anydb):
    txn = anydb.begin(sync=True, disable_wal=False)
    txn.put(b"a", b"1")
    txn.commit()
    txn = anydb.begin(disable_wal=True)
    txn.put(b"b", b"2")
    txn.commit()
    assert anydb.multi_get([b"a", b"b"]) == [b"1", b"2"]


def test_txn_id(tdb):
    a = tdb.begin()
    b = tdb.begin()
    assert a.id != b.id
    a.rollback()
    b.rollback()


# ---------------------------------------------------------------------------
# pessimistic: locks, timeouts, deadlocks
# ---------------------------------------------------------------------------


def test_get_for_update_conflict_times_out(tdb):
    tdb.put(b"a", b"1")
    t1 = tdb.begin()
    assert t1.get_for_update(b"a") == b"1"
    t2 = tdb.begin(lock_timeout_ms=100)
    t0 = time.monotonic()
    with pytest.raises(rdbpy.TimedOut) as ei:
        t2.get_for_update(b"a")
    assert time.monotonic() - t0 < 1.0
    assert ei.value.code == 9
    with pytest.raises(rdbpy.TimedOut):
        t2.put(b"a", b"2")
    with pytest.raises(rdbpy.TimedOut):
        t2.delete(b"a")
    # plain reads are never blocked
    assert t2.get(b"a") == b"1"
    assert tdb.get(b"a") == b"1"
    t1.put(b"a", b"mine")
    t1.commit()
    # lock released: t2 can proceed now and sees the committed value
    assert t2.get_for_update(b"a") == b"mine"
    t2.rollback()


def test_lock_timeout_zero_fails_immediately(tdb):
    t1 = tdb.begin()
    t1.put(b"a", b"1")
    t2 = tdb.begin(lock_timeout_ms=0)
    t0 = time.monotonic()
    with pytest.raises(rdbpy.TimedOut):
        t2.put(b"a", b"2")
    assert time.monotonic() - t0 < 0.1
    t1.rollback()
    t2.rollback()


def test_db_level_default_lock_timeout(path):
    db = rdbpy.TransactionDB(path(), lock_timeout_ms=50, default_lock_timeout_ms=50)
    try:
        t1 = db.begin()
        t1.put(b"a", b"1")
        t0 = time.monotonic()
        with pytest.raises(rdbpy.TimedOut):
            db.put(b"a", b"2")  # plain put also takes the lock
        with pytest.raises(rdbpy.TimedOut):
            db.begin().put(b"a", b"3")
        assert time.monotonic() - t0 < 1.0
        t1.rollback()
        db.put(b"a", b"2")
        assert db.get(b"a") == b"2"
    finally:
        db.close()


def test_shared_locks_allow_concurrent_readers(tdb):
    tdb.put(b"a", b"1")
    t1 = tdb.begin()
    t2 = tdb.begin()
    assert t1.get_for_update(b"a", exclusive=False) == b"1"
    assert t2.get_for_update(b"a", exclusive=False) == b"1"
    with pytest.raises(rdbpy.TimedOut):
        t2.put(b"a", b"2")  # upgrade blocked by t1's shared lock
    t1.rollback()
    t2.put(b"a", b"2")
    t2.commit()
    assert tdb.get(b"a") == b"2"


def test_lock_wait_succeeds_when_holder_commits(tdb):
    tdb.put(b"a", b"1")
    t1 = tdb.begin()
    t1.get_for_update(b"a")
    t2 = tdb.begin(lock_timeout_ms=2000)
    got = []

    def waiter():
        got.append(t2.get_for_update(b"a"))

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(0.1)
    assert th.is_alive()
    t1.put(b"a", b"2")
    t1.commit()
    th.join(timeout=3)
    assert not th.is_alive()
    assert got == [b"2"]
    t2.rollback()


def test_deadlock_detection(tdb):
    tdb.put(b"a", b"1")
    tdb.put(b"b", b"1")
    t1 = tdb.begin(lock_timeout_ms=5000, deadlock_detect=True)
    t2 = tdb.begin(lock_timeout_ms=5000, deadlock_detect=True)
    t1.put(b"a", b"t1")
    t2.put(b"b", b"t2")
    done = threading.Event()
    outcome = []

    def t1_waits_for_b():
        try:
            t1.put(b"b", b"t1")
            outcome.append("ok")
        except rdbpy.RocksDBError as e:
            outcome.append(type(e).__name__)
        done.set()

    th = threading.Thread(target=t1_waits_for_b)
    th.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    with pytest.raises(rdbpy.Deadlock) as ei:
        t2.put(b"a", b"t2")  # closes the cycle: detected at once
    assert time.monotonic() - t0 < 1.0
    assert isinstance(ei.value, rdbpy.Busy)
    assert ei.value.subcode == 5
    t2.rollback()  # frees b, t1 proceeds
    assert done.wait(3)
    assert outcome == ["ok"]
    t1.commit()
    assert tdb.get(b"a") == b"t1"
    assert tdb.get(b"b") == b"t1"


def test_no_deadlock_detect_times_out_instead(tdb):
    t1 = tdb.begin(lock_timeout_ms=300)
    t2 = tdb.begin(lock_timeout_ms=300)
    t1.put(b"a", b"1")
    t2.put(b"b", b"1")
    th = threading.Thread(target=lambda: pytest.raises(rdbpy.RocksDBError, t1.put, b"b", b"1"))
    th.start()
    time.sleep(0.05)
    with pytest.raises(rdbpy.TimedOut):
        t2.put(b"a", b"1")
    th.join()
    t1.rollback()
    t2.rollback()


def test_expiration(path):
    db = rdbpy.TransactionDB(path())
    try:
        txn = db.begin(expiration_ms=50)
        txn.put(b"a", b"1")
        time.sleep(0.15)
        with pytest.raises(rdbpy.Expired):
            txn.commit()
        assert not txn.active
        assert db.get(b"a") is None
    finally:
        db.close()


def test_lock_limit(path):
    db = rdbpy.TransactionDB(path(), max_num_locks=2)
    try:
        txn = db.begin()
        txn.put(b"a", b"1")
        txn.put(b"b", b"1")
        with pytest.raises(rdbpy.LockLimit) as ei:
            txn.put(b"c", b"1")
        assert ei.value.subcode == 3
        txn.rollback()
    finally:
        db.close()


def test_pessimistic_commit_after_snapshot_write_conflict(tdb):
    # put (no snapshot) locks the key: the other writer times out, no Busy.
    tdb.put(b"a", b"1")
    t1 = tdb.begin()
    t1.put(b"a", b"t1")
    with pytest.raises(rdbpy.TimedOut):
        tdb.put(b"a", b"outside")
    t1.commit()
    assert tdb.get(b"a") == b"t1"


def test_pessimistic_put_with_snapshot_detects_conflict(tdb):
    tdb.put(b"a", b"1")
    t1 = tdb.begin(set_snapshot=True)
    tdb.put(b"a", b"outside")
    with pytest.raises(rdbpy.Busy):
        t1.put(b"a", b"t1")
    t1.rollback()


# ---------------------------------------------------------------------------
# optimistic: validation at commit
# ---------------------------------------------------------------------------


def test_optimistic_commit_conflict_on_written_key(odb):
    odb.put(b"a", b"1")
    t1 = odb.begin()
    t1.put(b"a", b"t1")
    odb.put(b"a", b"outside")  # no locks: this goes through
    with pytest.raises(rdbpy.Busy) as ei:
        t1.commit()
    assert ei.value.code == 11
    assert not t1.active
    assert odb.get(b"a") == b"outside"


def test_optimistic_two_txns_first_wins(odb):
    odb.put(b"counter", b"0")
    t1 = odb.begin()
    t2 = odb.begin()
    v1 = int(t1.get_for_update(b"counter"))
    v2 = int(t2.get_for_update(b"counter"))
    t1.put(b"counter", b"%d" % (v1 + 1))
    t2.put(b"counter", b"%d" % (v2 + 1))
    t1.commit()
    with pytest.raises(rdbpy.Busy):
        t2.commit()
    assert odb.get(b"counter") == b"1"


def test_optimistic_untracked_read_does_not_conflict(odb):
    odb.put(b"a", b"1")
    t1 = odb.begin()
    assert t1.get(b"a") == b"1"  # plain get: not tracked
    odb.put(b"a", b"2")
    t1.put(b"b", b"1")
    t1.commit()  # fine
    assert odb.get(b"b") == b"1"


def test_optimistic_tracked_read_conflicts(odb):
    odb.put(b"a", b"1")
    t1 = odb.begin()
    assert t1.get_for_update(b"a") == b"1"
    odb.put(b"a", b"2")
    t1.put(b"b", b"1")
    with pytest.raises(rdbpy.Busy):
        t1.commit()
    assert odb.get(b"b") is None


def test_optimistic_tracked_missing_key_conflicts_on_insert(odb):
    t1 = odb.begin()
    assert t1.get_for_update(b"new") is None
    odb.put(b"new", b"someone")
    t1.put(b"other", b"1")
    with pytest.raises(rdbpy.Busy):
        t1.commit()


def test_optimistic_no_conflict_commits(odb):
    odb.put(b"a", b"1")
    t1 = odb.begin(set_snapshot=True)
    assert t1.get_for_update(b"a") == b"1"
    odb.put(b"unrelated", b"x")
    t1.put(b"a", b"2")
    t1.commit()
    assert odb.get(b"a") == b"2"


def test_optimistic_serial_policy(path):
    db = rdbpy.OptimisticTransactionDB(path(), validate_policy="serial")
    try:
        t = db.begin()
        t.put(b"a", b"1")
        db.put(b"a", b"2")
        with pytest.raises(rdbpy.Busy):
            t.commit()
    finally:
        db.close()
    with pytest.raises(ValueError):
        rdbpy.OptimisticTransactionDB(path(), validate_policy="nope")


def test_optimistic_survives_flush_with_history(path):
    # The txn outlives a memtable flush; with memtable history kept the commit
    # validates (TryAgain would mean history was too short).
    db = rdbpy.OptimisticTransactionDB(
        path(), rdbpy.Options(create_if_missing=True, max_write_buffer_size_to_maintain=-1)
    )
    try:
        db.put(b"a", b"1")
        t = db.begin()
        t.get_for_update(b"a")
        for i in range(100):
            db.put(b"k%d" % i, b"x" * 100)
        db.flush()
        t.put(b"b", b"1")
        t.commit()
        assert db.get(b"b") == b"1"
    finally:
        db.close()
