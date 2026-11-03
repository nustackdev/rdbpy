"""Snapshots are honoured by every read path: write after the snapshot,
read through it, see the old value."""

import pytest

import rdbpy


def test_db_get_honours_snapshot(db):
    db.put(b"a", b"old")
    snap = db.snapshot()
    db.put(b"a", b"new")
    db.put(b"b", b"born")
    assert db.get(b"a", snapshot=snap) == b"old"
    assert db.get(b"b", snapshot=snap) is None
    assert db.get(b"a") == b"new"
    assert db.multi_get([b"a", b"b"], snapshot=snap) == [b"old", None]
    assert db.multi_get([b"a", b"b"]) == [b"new", b"born"]
    snap.release()


def test_snapshot_sees_deletes_as_present(db):
    db.put(b"a", b"old")
    with db.snapshot() as snap:
        db.delete(b"a")
        assert db.get(b"a", snapshot=snap) == b"old"
        assert db.get(b"a") is None
    assert snap.released


def test_db_iterator_honours_snapshot(db):
    db.put(b"a", b"1")
    db.put(b"b", b"2")
    snap = db.snapshot()
    db.put(b"b", b"2b")
    db.put(b"c", b"3")
    db.delete(b"a")
    assert list(db.iterator(snapshot=snap)) == [(b"a", b"1"), (b"b", b"2")]
    assert list(db.iterator(snapshot=snap, reverse=True, keys_only=True)) == [b"b", b"a"]
    assert db.iterator(snapshot=snap, prefix=b"b").next_batch() == [(b"b", b"2")]
    assert list(db.iterator()) == [(b"b", b"2b"), (b"c", b"3")]


def test_snapshot_sequence_and_release(db):
    db.put(b"a", b"1")
    snap = db.snapshot()
    seq = snap.sequence
    assert seq == db.latest_sequence_number
    db.put(b"a", b"2")
    assert db.snapshot().sequence > seq
    snap.release()
    assert snap.released
    snap.release()  # idempotent
    with pytest.raises(RuntimeError):
        db.get(b"a", snapshot=snap)
    with pytest.raises(RuntimeError):
        snap.sequence


def test_snapshot_of_other_db_rejected(db, path):
    other = rdbpy.DB(path())
    try:
        snap = other.snapshot()
        with pytest.raises(ValueError):
            db.get(b"a", snapshot=snap)
        with pytest.raises(TypeError):
            db.get(b"a", snapshot=object())
    finally:
        other.close()


def test_db_close_releases_snapshots(path):
    db = rdbpy.DB(path())
    snap = db.snapshot()
    db.close()
    assert snap.released
    snap.release()


@pytest.mark.parametrize("kind", ["pessimistic", "optimistic"])
def test_txn_get_honours_explicit_snapshot(path, kind):
    cls = rdbpy.TransactionDB if kind == "pessimistic" else rdbpy.OptimisticTransactionDB
    db = cls(path())
    try:
        db.put(b"a", b"old")
        snap = db.snapshot()
        db.put(b"a", b"new")
        txn = db.begin()
        assert txn.get(b"a", snapshot=snap) == b"old"
        assert txn.get(b"a") == b"new"
        # own writes win over the snapshot
        txn.put(b"a", b"mine")
        assert txn.get(b"a", snapshot=snap) == b"mine"
        assert txn.get(b"b", snapshot=snap) is None
        txn.rollback()
        snap.release()
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["pessimistic", "optimistic"])
def test_txn_own_snapshot_is_default_for_reads(path, kind):
    cls = rdbpy.TransactionDB if kind == "pessimistic" else rdbpy.OptimisticTransactionDB
    db = cls(path())
    try:
        db.put(b"a", b"old")
        txn = db.begin(set_snapshot=True)
        assert txn.snapshot is not None
        db.put(b"a", b"new")
        db.put(b"b", b"born")
        assert txn.get(b"a") == b"old"
        assert txn.get(b"b") is None
        assert list(txn.iterator()) == [(b"a", b"old")]
        assert txn.iterator(keys_only=True).next_batch() == [b"a"]
        # the view is also usable on the plain db
        assert db.get(b"a", snapshot=txn.snapshot) == b"old"
        assert db.get(b"a") == b"new"
        txn.rollback()
    finally:
        db.close()


def test_txn_set_snapshot_later(tdb):
    tdb.put(b"a", b"1")
    txn = tdb.begin()
    assert txn.snapshot is None
    tdb.put(b"a", b"2")
    txn.set_snapshot()
    view = txn.snapshot
    tdb.put(b"a", b"3")
    assert txn.get(b"a") == b"2"
    assert tdb.get(b"a", snapshot=view) == b"2"
    txn.set_snapshot()  # moves forward, old view is gone
    assert view.released
    assert txn.get(b"a") == b"3"
    txn.clear_snapshot()
    assert txn.snapshot is None
    tdb.put(b"a", b"4")
    assert txn.get(b"a") == b"4"
    txn.rollback()


def test_txn_snapshot_view_dies_with_txn(tdb):
    txn = tdb.begin(set_snapshot=True)
    view = txn.snapshot
    txn.commit()
    assert view.released
    with pytest.raises(RuntimeError):
        tdb.get(b"a", snapshot=view)


def test_get_for_update_honours_snapshot_pessimistic(tdb):
    tdb.put(b"a", b"old")
    txn = tdb.begin(set_snapshot=True)
    tdb.put(b"a", b"new")
    # key changed after the snapshot: a validated lock must fail
    with pytest.raises(rdbpy.Busy):
        txn.get_for_update(b"a")
    # validate=False reads latest and locks
    assert txn.get_for_update(b"a", validate=False) == b"new"
    txn.rollback()

    # an explicit snapshot picks what is read; conflict checks always use
    # the transaction's own snapshot (none here), so this locks and reads old
    txn = tdb.begin()
    snap = tdb.snapshot()
    tdb.put(b"a", b"newer")
    assert txn.get_for_update(b"a", snapshot=snap) == b"new"
    assert txn.get_for_update(b"a") == b"newer"
    txn.rollback()
    snap.release()


def test_get_for_update_unchanged_key_passes_pessimistic(tdb):
    tdb.put(b"a", b"old")
    tdb.put(b"b", b"x")
    txn = tdb.begin(set_snapshot=True)
    tdb.put(b"b", b"y")  # unrelated key
    assert txn.get_for_update(b"a") == b"old"
    txn.put(b"a", b"mine")
    txn.commit()
    assert tdb.get(b"a") == b"mine"


def test_get_for_update_honours_snapshot_optimistic(odb):
    odb.put(b"a", b"old")
    txn = odb.begin(set_snapshot=True)
    odb.put(b"a", b"new")
    assert txn.get_for_update(b"a") == b"old"  # reads at the snapshot
    txn.put(b"b", b"1")
    with pytest.raises(rdbpy.Busy):  # tracked read conflicts at commit
        txn.commit()
    assert not txn.active
    assert odb.get(b"b") is None


def test_snapshot_from_db_is_pinned_across_flush(db):
    db.put(b"a", b"1")
    snap = db.snapshot()
    for i in range(200):
        db.put(b"k%04d" % i, b"x" * 1000)
    db.put(b"a", b"2")
    db.flush()
    db.compact_range()
    assert db.get(b"a", snapshot=snap) == b"1"
    assert len(list(db.iterator(snapshot=snap))) == 1
    snap.release()
