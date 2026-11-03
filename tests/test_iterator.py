"""Iterators: seeks, direction, bounds, prefix, keys_only, batches, txn merge."""

import pytest

import rdbpy
from conftest import fill


def keys(it):
    return [k for k, _ in it]


def test_forward_and_reverse(db):
    fill(db, 5)
    assert keys(db.iterator()) == [b"k%04d" % i for i in range(5)]
    assert keys(db.iterator(reverse=True)) == [b"k%04d" % i for i in range(4, -1, -1)]
    assert list(db.iterator(keys_only=True)) == [b"k%04d" % i for i in range(5)]
    assert list(db.iterator(keys_only=True, reverse=True))[0] == b"k0004"


def test_items_are_bytes(db):
    db.put(b"a", b"1")
    rows = list(db.iterator())
    assert rows == [(b"a", b"1")]
    assert isinstance(rows[0][0], bytes)


def test_empty_db(db):
    assert list(db.iterator()) == []
    assert db.iterator().next_batch() == []
    it = db.iterator()
    it.seek_to_first()
    assert not it.valid()
    with pytest.raises(RuntimeError):
        it.key()


def test_raw_cursor(db):
    fill(db, 10)
    it = db.iterator()
    it.seek(b"k0003")
    assert it.valid()
    assert it.key() == b"k0003"
    assert it.value() == b"v0003"
    assert it.item() == (b"k0003", b"v0003")
    it.next()
    assert it.key() == b"k0004"
    it.prev()
    assert it.key() == b"k0003"
    it.seek_to_last()
    assert it.key() == b"k0009"
    it.next()
    assert not it.valid()
    it.seek_to_first()
    assert it.key() == b"k0000"
    it.prev()
    assert not it.valid()
    it.status()


def test_seek_between_keys(db):
    fill(db, 10)
    it = db.iterator()
    it.seek(b"k0003x")
    assert it.key() == b"k0004"
    it.seek_for_prev(b"k0003x")
    assert it.key() == b"k0003"
    it.seek(b"zzz")
    assert not it.valid()
    it.seek_for_prev(b"\x00")
    assert not it.valid()
    it.seek_for_prev(b"zzz")
    assert it.key() == b"k0009"


def test_seek_then_iterate_in_direction(db):
    fill(db, 10)
    it = db.iterator()
    it.seek(b"k0007")
    assert keys(it) == [b"k0007", b"k0008", b"k0009"]
    it = db.iterator(reverse=True)
    it.seek_for_prev(b"k0002")
    assert keys(it) == [b"k0002", b"k0001", b"k0000"]


def test_bounds(db):
    fill(db, 10)
    assert keys(db.iterator(lower=b"k0003", upper=b"k0006")) == [b"k0003", b"k0004", b"k0005"]
    assert keys(db.iterator(lower=b"k0003", upper=b"k0006", reverse=True)) == [
        b"k0005",
        b"k0004",
        b"k0003",
    ]
    assert keys(db.iterator(lower=b"k0008")) == [b"k0008", b"k0009"]
    assert keys(db.iterator(upper=b"k0002")) == [b"k0000", b"k0001"]
    # seeks cannot leave the window
    it = db.iterator(lower=b"k0003", upper=b"k0006")
    it.seek(b"k0000")
    assert it.key() == b"k0003"
    it.seek(b"k0009")
    assert not it.valid()
    it.seek_for_prev(b"k0009")
    assert it.key() == b"k0005"
    it.seek_to_last()
    assert it.key() == b"k0005"
    it.seek_to_first()
    assert it.key() == b"k0003"


def test_prefix(db):
    fill(db, 3, prefix=b"a/")
    fill(db, 3, prefix=b"b/")
    fill(db, 3, prefix=b"c/")
    assert keys(db.iterator(prefix=b"b/")) == [b"b/0000", b"b/0001", b"b/0002"]
    assert keys(db.iterator(prefix=b"b/", reverse=True)) == [b"b/0002", b"b/0001", b"b/0000"]
    assert keys(db.iterator(prefix=b"zz")) == []
    with pytest.raises(ValueError):
        db.iterator(prefix=b"b/", lower=b"a")


def test_prefix_0xff_edge(db):
    db.put(b"\xff\xff", b"1")
    db.put(b"\xff\xffa", b"2")
    db.put(b"\xfe", b"0")
    assert keys(db.iterator(prefix=b"\xff\xff")) == [b"\xff\xff", b"\xff\xffa"]
    assert keys(db.iterator(prefix=b"\xfe\xff")) == []
    assert rdbpy.next_prefix(b"ab") == b"ac"
    assert rdbpy.next_prefix(b"a\xff") == b"b"
    assert rdbpy.next_prefix(b"\xff") is None
    assert rdbpy.next_prefix(b"") is None


def test_with_prefix_extractor_total_order(path):
    o = rdbpy.Options(create_if_missing=True, prefix_extractor_len=2, bloom_bits_per_key=10)
    with rdbpy.DB(path(), o) as db:
        fill(db, 3, prefix=b"aa")
        fill(db, 3, prefix=b"bb")
        db.flush()
        it = db.iterator()
        it.seek(b"ab")
        assert it.key() == b"bb0000"  # total order seek crosses prefixes
        assert keys(db.iterator(prefix=b"bb")) == [b"bb0000", b"bb0001", b"bb0002"]


def test_next_batch(db):
    fill(db, 10)
    it = db.iterator()
    assert it.next_batch(4) == [(b"k%04d" % i, b"v%04d" % i) for i in range(4)]
    assert [k for k, _ in it.next_batch(4)] == [b"k%04d" % i for i in range(4, 8)]
    assert [k for k, _ in it.next_batch(4)] == [b"k0008", b"k0009"]
    assert it.next_batch(4) == []
    it = db.iterator(keys_only=True, reverse=True)
    assert it.next_batch(3) == [b"k0009", b"k0008", b"k0007"]
    assert it.next_batch() == [b"k%04d" % i for i in range(6, -1, -1)]
    with pytest.raises(ValueError):
        it.next_batch(0)


def test_next_batch_after_seek(db):
    fill(db, 10)
    it = db.iterator(reverse=True)
    it.seek_for_prev(b"k0004")
    assert [k for k, _ in it.next_batch(2)] == [b"k0004", b"k0003"]
    assert [k for k, _ in it.next_batch(100)] == [b"k0002", b"k0001", b"k0000"]


def test_iterator_is_live_view_at_latest(db):
    db.put(b"a", b"1")
    it = db.iterator()
    db.put(b"b", b"2")  # after the iterator was created: not visible
    assert keys(it) == [b"a"]
    assert keys(db.iterator()) == [b"a", b"b"]


def test_close_and_context_manager(db):
    db.put(b"a", b"1")
    with db.iterator() as it:
        assert keys(it) == [b"a"]
    assert it.closed
    with pytest.raises(RuntimeError):
        it.seek_to_first()
    it.close()  # idempotent


def test_many_iterators(db):
    fill(db, 10)
    its = [db.iterator(lower=b"k%04d" % i) for i in range(10)]
    for i, it in enumerate(its):
        assert len(list(it)) == 10 - i
    del its


def test_txn_iterator_merges_own_writes(tdb):
    fill(tdb, 5)
    txn = tdb.begin()
    txn.put(b"k0002", b"mine")
    txn.put(b"k0009", b"new")
    txn.delete(b"k0000")
    rows = dict(txn.iterator())
    assert rows == {
        b"k0001": b"v0001",
        b"k0002": b"mine",
        b"k0003": b"v0003",
        b"k0004": b"v0004",
        b"k0009": b"new",
    }
    assert list(txn.iterator(keys_only=True, reverse=True))[0] == b"k0009"
    assert keys(txn.iterator(prefix=b"k000", lower=None)) == [
        b"k0001",
        b"k0002",
        b"k0003",
        b"k0004",
        b"k0009",
    ]
    assert keys(txn.iterator(lower=b"k0002", upper=b"k0004")) == [b"k0002", b"k0003"]
    it = txn.iterator()
    assert it.next_batch(2) == [(b"k0001", b"v0001"), (b"k0002", b"mine")]
    txn.rollback()
    with pytest.raises(RuntimeError):
        it.next_batch(2)


def test_optimistic_txn_iterator(odb):
    fill(odb, 3)
    txn = odb.begin()
    txn.put(b"k0001", b"mine")
    assert dict(txn.iterator())[b"k0001"] == b"mine"
    txn.commit()
    assert odb.get(b"k0001") == b"mine"


def test_iterator_from_txn_after_commit_raises(tdb):
    tdb.put(b"a", b"1")
    txn = tdb.begin()
    it = txn.iterator()
    txn.commit()
    assert it.closed
    with pytest.raises(RuntimeError):
        it.seek_to_first()


def test_db_close_invalidates_iterators(path):
    db = rdbpy.DB(path())
    db.put(b"a", b"1")
    it = db.iterator()
    db.close()
    assert it.closed
    with pytest.raises(RuntimeError):
        list(it)
