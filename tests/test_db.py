"""Plain DB: open modes, options, point ops, batches, maintenance."""

import os

import pytest

import rdbpy
from conftest import fill


def test_open_put_get_delete(db):
    assert db.get(b"a") is None
    db.put(b"a", b"1")
    assert db.get(b"a") == b"1"
    db.delete(b"a")
    assert db.get(b"a") is None
    db.delete(b"never")  # deleting a missing key is fine


def test_default_options_create(path):
    p = path()
    with rdbpy.DB(p) as db:
        db.put(b"a", b"1")
    assert os.path.exists(os.path.join(p, "CURRENT"))


def test_open_missing_without_create_raises(path):
    with pytest.raises(rdbpy.InvalidArgument):
        rdbpy.DB(path(), rdbpy.Options(create_if_missing=False))


def test_error_if_exists(path):
    p = path()
    rdbpy.DB(p).close()
    with pytest.raises(rdbpy.InvalidArgument):
        rdbpy.DB(p, rdbpy.Options(create_if_missing=True, error_if_exists=True))


def test_second_open_of_same_dir_is_io_error(path):
    p = path()
    db = rdbpy.DB(p)
    try:
        with pytest.raises(rdbpy.RocksIOError):
            rdbpy.DB(p)
    finally:
        db.close()


def test_bytes_only(db):
    with pytest.raises(TypeError):
        db.put("a", b"1")
    with pytest.raises(TypeError):
        db.put(b"a", "1")
    with pytest.raises(TypeError):
        db.get("a")


def test_empty_key_and_value(db):
    db.put(b"", b"")
    assert db.get(b"") == b""
    db.put(b"k", b"")
    assert db.get(b"k") == b""


def test_large_values(db):
    v = os.urandom(2_000_000)
    db.put(b"big", v)
    assert db.get(b"big") == v


def test_multi_get(db):
    fill(db, 5)
    out = db.multi_get([b"k0001", b"nope", b"k0004"])
    assert out == [b"v0001", None, b"v0004"]
    assert db.multi_get([]) == []
    assert db.multi_get(iter([b"k0000"])) == [b"v0000"]
    with pytest.raises(TypeError):
        db.multi_get(["k0000"])


def test_write_batch(db):
    db.put(b"gone", b"x")
    wb = rdbpy.WriteBatch()
    wb.put(b"a", b"1")
    wb.put(b"b", b"2")
    wb.delete(b"gone")
    assert len(wb) == 3
    assert wb.count() == 3
    db.write(wb)
    assert db.get(b"a") == b"1"
    assert db.get(b"b") == b"2"
    assert db.get(b"gone") is None
    wb.clear()
    assert len(wb) == 0
    db.write(wb)  # empty batch is a no-op


def test_write_options(db):
    db.put(b"a", b"1", sync=True)
    db.put(b"b", b"2", disable_wal=True)
    wb = rdbpy.WriteBatch()
    wb.put(b"c", b"3")
    db.write(wb, sync=True)
    assert db.multi_get([b"a", b"b", b"c"]) == [b"1", b"2", b"3"]


def test_close_and_use_raises(path):
    db = rdbpy.DB(path())
    assert not db.closed
    db.close()
    assert db.closed
    db.close()  # idempotent
    for call in (
        lambda: db.get(b"a"),
        lambda: db.put(b"a", b"1"),
        lambda: db.delete(b"a"),
        lambda: db.iterator(),
        lambda: db.snapshot(),
        lambda: db.write(rdbpy.WriteBatch()),
        lambda: db.flush(),
    ):
        with pytest.raises(RuntimeError):
            call()
    assert "closed" in repr(db)


def test_context_manager_closes(path):
    with rdbpy.DB(path()) as db:
        db.put(b"a", b"1")
    assert db.closed


def test_reopen_persists(path):
    p = path()
    with rdbpy.DB(p) as db:
        db.put(b"a", b"1")
    with rdbpy.DB(p, rdbpy.Options(create_if_missing=False)) as db:
        assert db.get(b"a") == b"1"


def test_read_only(path):
    p = path()
    with rdbpy.DB(p) as db:
        db.put(b"a", b"1")
    with rdbpy.DB(p, read_only=True) as ro:
        assert ro.get(b"a") == b"1"
        with pytest.raises(rdbpy.NotSupported):
            ro.put(b"b", b"2")


def test_secondary_catches_up(path, tmp_path):
    p = path()
    primary = rdbpy.DB(p)
    primary.put(b"a", b"1")
    primary.flush()
    secondary = rdbpy.DB(p, secondary_path=str(tmp_path / "secondary"))
    try:
        assert secondary.get(b"a") == b"1"
        primary.put(b"b", b"2")
        primary.flush()
        secondary.try_catch_up_with_primary()
        assert secondary.get(b"b") == b"2"
    finally:
        secondary.close()
        primary.close()


def test_flush_compact_property(db):
    fill(db, 50)
    db.flush()
    db.flush_wal(sync=True)
    db.compact_range()
    db.compact_range(b"k0010", b"k0020")
    assert db.get_property("rocksdb.estimate-num-keys") is not None
    assert db.get_property("rocksdb.no-such-property") is None
    assert db.latest_sequence_number >= 50


def test_destroy_db(path):
    p = path()
    with rdbpy.DB(p) as db:
        db.put(b"a", b"1")
    rdbpy.destroy_db(p)
    with rdbpy.DB(p) as db:
        assert db.get(b"a") is None


def test_path_and_options_attrs(path):
    p = path()
    opts = rdbpy.Options(create_if_missing=True)
    with rdbpy.DB(p, opts) as db:
        assert db.path == p
        assert db.options is opts
    with rdbpy.DB(os.fsencode(p)) as db:
        assert db.path == p


def test_version():
    assert rdbpy.__version__ == "0.3.0"
    assert rdbpy.rocksdb_version() == "6.29.5"
