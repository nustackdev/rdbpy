"""Exception classes mapped from rocksdb::Status.

One base class, one subclass per status code. Transaction conflicts are
distinct classes so callers can decide what to retry: Busy, TryAgain,
TimedOut (lock wait), Deadlock (a Busy with the deadlock subcode),
LockLimit and Expired.
"""


class RocksDBError(Exception):
    """Base class. `code` and `subcode` are the raw rocksdb::Status values."""

    code: int = 0
    subcode: int = 0

    def __init__(self, message: str = "", code: int = 0, subcode: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode

    @property
    def message(self) -> str:
        return str(self.args[0]) if self.args else ""


class NotFound(RocksDBError):
    """Key missing. Reads return None instead; raised only by other paths."""


class Corruption(RocksDBError):
    pass


class NotSupported(RocksDBError):
    pass


class InvalidArgument(RocksDBError):
    pass


class RocksIOError(RocksDBError):
    pass


class MergeInProgress(RocksDBError):
    pass


class Incomplete(RocksDBError):
    pass


class ShutdownInProgress(RocksDBError):
    pass


class TimedOut(RocksDBError):
    """A lock (or mutex) wait exceeded its timeout."""


class Aborted(RocksDBError):
    pass


class LockLimit(RocksDBError):
    """TransactionDBOptions.max_num_locks reached (rocksdb reports it as Busy
    or Aborted depending on the path, so it stands on its own)."""


class Busy(RocksDBError):
    """Write conflict: the key changed after the transaction's snapshot, or
    an optimistic commit failed validation."""


class Deadlock(Busy):
    """Lock wait would form a cycle (needs deadlock_detect=True)."""


class Expired(RocksDBError):
    """Transaction expiration reached before commit."""


class TryAgain(RocksDBError):
    """Memtable history too short to validate; retry (see
    max_write_buffer_size_to_maintain)."""


class CompactionTooLarge(RocksDBError):
    pass


class ColumnFamilyDropped(RocksDBError):
    pass


# rocksdb::Status::Code -> class
_BY_CODE = {
    1: NotFound,
    2: Corruption,
    3: NotSupported,
    4: InvalidArgument,
    5: RocksIOError,
    6: MergeInProgress,
    7: Incomplete,
    8: ShutdownInProgress,
    9: TimedOut,
    10: Aborted,
    11: Busy,
    12: Expired,
    13: TryAgain,
    14: CompactionTooLarge,
    15: ColumnFamilyDropped,
}

_SUBCODE_LOCK_LIMIT = 3
_SUBCODE_DEADLOCK = 5


def error_for(code: int, subcode: int, message: str) -> RocksDBError:
    """Build the exception for a non-ok status."""
    cls = _BY_CODE.get(code, RocksDBError)
    if code == 11 and subcode == _SUBCODE_DEADLOCK:
        cls = Deadlock
    elif code in (10, 11) and subcode == _SUBCODE_LOCK_LIMIT:
        cls = LockLimit
    return cls(message, code, subcode)


__all__ = [
    "RocksDBError",
    "NotFound",
    "Corruption",
    "NotSupported",
    "InvalidArgument",
    "RocksIOError",
    "MergeInProgress",
    "Incomplete",
    "ShutdownInProgress",
    "TimedOut",
    "Aborted",
    "LockLimit",
    "Busy",
    "Deadlock",
    "Expired",
    "TryAgain",
    "CompactionTooLarge",
    "ColumnFamilyDropped",
    "error_for",
]
