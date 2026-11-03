"""Status code mapping and the exception hierarchy."""

import pytest

import rdbpy
from rdbpy import errors


def test_hierarchy():
    for cls in (
        rdbpy.NotFound, rdbpy.Corruption, rdbpy.NotSupported, rdbpy.InvalidArgument,
        rdbpy.RocksIOError, rdbpy.MergeInProgress, rdbpy.Incomplete, rdbpy.ShutdownInProgress,
        rdbpy.TimedOut, rdbpy.Aborted, rdbpy.Busy, rdbpy.Expired, rdbpy.TryAgain,
        rdbpy.CompactionTooLarge, rdbpy.ColumnFamilyDropped,
    ):
        assert issubclass(cls, rdbpy.RocksDBError)
    assert issubclass(rdbpy.Deadlock, rdbpy.Busy)
    assert issubclass(rdbpy.LockLimit, rdbpy.RocksDBError)
    assert not issubclass(rdbpy.TimedOut, rdbpy.Busy)
    assert not issubclass(rdbpy.TryAgain, rdbpy.Busy)


def test_error_for_mapping():
    assert type(errors.error_for(11, 0, "x")) is rdbpy.Busy
    assert type(errors.error_for(11, 5, "x")) is rdbpy.Deadlock
    assert type(errors.error_for(9, 2, "x")) is rdbpy.TimedOut
    assert type(errors.error_for(13, 0, "x")) is rdbpy.TryAgain
    assert type(errors.error_for(10, 3, "x")) is rdbpy.LockLimit
    assert type(errors.error_for(11, 3, "x")) is rdbpy.LockLimit
    assert type(errors.error_for(1, 0, "x")) is rdbpy.NotFound
    assert type(errors.error_for(99, 0, "x")) is rdbpy.RocksDBError
    e = errors.error_for(9, 2, "lock timeout")
    assert e.code == 9 and e.subcode == 2
    assert e.message == "lock timeout"
    assert str(e) == "lock timeout"


def test_raised_errors_carry_codes(path):
    with pytest.raises(rdbpy.InvalidArgument) as ei:
        rdbpy.DB(path(), rdbpy.Options(create_if_missing=False))
    assert ei.value.code == 4
    assert "does not exist" in str(ei.value)
