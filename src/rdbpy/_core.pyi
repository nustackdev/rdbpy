"""Type stubs for rdbpy._core."""

from collections.abc import Iterable
from os import PathLike
from typing import Literal

StrPath = str | bytes | PathLike[str] | PathLike[bytes]
Compression = Literal["none", "snappy", "zlib", "bz2", "lz4", "lz4hc", "zstd"]
CompactionStyle = Literal["level", "universal", "fifo"]

def next_prefix(prefix: bytes) -> bytes | None: ...
def destroy_db(path: StrPath, options: Options | None = None) -> None: ...
def rocksdb_version() -> str: ...

class Options:
    def __init__(
        self,
        *,
        create_if_missing: bool = ...,
        error_if_exists: bool = ...,
        paranoid_checks: bool = ...,
        max_open_files: int = ...,
        use_fsync: bool = ...,
        wal_dir: StrPath = ...,
        db_log_dir: StrPath = ...,
        max_background_jobs: int = ...,
        max_log_file_size: int = ...,
        keep_log_file_num: int = ...,
        max_total_wal_size: int = ...,
        db_write_buffer_size: int = ...,
        allow_mmap_reads: bool = ...,
        allow_mmap_writes: bool = ...,
        use_direct_reads: bool = ...,
        use_direct_io_for_flush_and_compaction: bool = ...,
        bytes_per_sync: int = ...,
        wal_bytes_per_sync: int = ...,
        allow_concurrent_memtable_write: bool = ...,
        manual_wal_flush: bool = ...,
        avoid_unnecessary_blocking_io: bool = ...,
        atomic_flush: bool = ...,
        wal_ttl_seconds: int = ...,
        wal_size_limit_mb: int = ...,
        write_buffer_size: int = ...,
        max_write_buffer_number: int = ...,
        min_write_buffer_number_to_merge: int = ...,
        max_write_buffer_size_to_maintain: int = ...,
        compression: Compression | int = ...,
        bottommost_compression: Compression | int = ...,
        num_levels: int = ...,
        level0_file_num_compaction_trigger: int = ...,
        level0_slowdown_writes_trigger: int = ...,
        level0_stop_writes_trigger: int = ...,
        target_file_size_base: int = ...,
        target_file_size_multiplier: int = ...,
        max_bytes_for_level_base: int = ...,
        max_bytes_for_level_multiplier: float = ...,
        level_compaction_dynamic_level_bytes: bool = ...,
        disable_auto_compactions: bool = ...,
        compaction_style: CompactionStyle = ...,
        max_compaction_bytes: int = ...,
        optimize_filters_for_hits: bool = ...,
        memtable_prefix_bloom_size_ratio: float = ...,
        prefix_extractor_len: int = ...,
        block_cache_size: int | None = ...,
        block_size: int = ...,
        block_restart_interval: int = ...,
        bloom_bits_per_key: float = ...,
        cache_index_and_filter_blocks: bool = ...,
        pin_l0_filter_and_index_blocks_in_cache: bool = ...,
        pin_top_level_index_and_filter: bool = ...,
        partition_filters: bool = ...,
        whole_key_filtering: bool = ...,
        format_version: int = ...,
        optimize_filters_for_memory: bool = ...,
    ) -> None: ...
    create_if_missing: bool
    error_if_exists: bool
    paranoid_checks: bool
    max_open_files: int
    use_fsync: bool
    wal_dir: str
    db_log_dir: str
    max_background_jobs: int
    max_log_file_size: int
    keep_log_file_num: int
    max_total_wal_size: int
    db_write_buffer_size: int
    allow_mmap_reads: bool
    allow_mmap_writes: bool
    use_direct_reads: bool
    use_direct_io_for_flush_and_compaction: bool
    bytes_per_sync: int
    wal_bytes_per_sync: int
    allow_concurrent_memtable_write: bool
    manual_wal_flush: bool
    avoid_unnecessary_blocking_io: bool
    atomic_flush: bool
    wal_ttl_seconds: int
    wal_size_limit_mb: int
    write_buffer_size: int
    max_write_buffer_number: int
    min_write_buffer_number_to_merge: int
    max_write_buffer_size_to_maintain: int
    compression: str
    bottommost_compression: str
    num_levels: int
    level0_file_num_compaction_trigger: int
    level0_slowdown_writes_trigger: int
    level0_stop_writes_trigger: int
    target_file_size_base: int
    target_file_size_multiplier: int
    max_bytes_for_level_base: int
    max_bytes_for_level_multiplier: float
    level_compaction_dynamic_level_bytes: bool
    disable_auto_compactions: bool
    compaction_style: str
    max_compaction_bytes: int
    optimize_filters_for_hits: bool
    memtable_prefix_bloom_size_ratio: float
    prefix_extractor_len: int
    block_cache_size: int | None
    block_size: int
    block_restart_interval: int
    bloom_bits_per_key: float
    cache_index_and_filter_blocks: bool
    pin_l0_filter_and_index_blocks_in_cache: bool
    pin_top_level_index_and_filter: bool
    partition_filters: bool
    whole_key_filtering: bool
    format_version: int
    optimize_filters_for_memory: bool

class WriteBatch:
    """Batched writes applied atomically by DB.write().

    One thread at a time: do not close, release or end it from one thread
    while another thread is using it.
    """

    def put(self, key: bytes, value: bytes) -> None: ...
    def delete(self, key: bytes) -> None: ...
    def single_delete(self, key: bytes) -> None: ...
    def clear(self) -> None: ...
    def count(self) -> int: ...
    def __len__(self) -> int: ...

class Snapshot:
    """Point-in-time read view; release() frees it, DB.close() invalidates it.

    One thread at a time: do not close, release or end it from one thread
    while another thread is using it.
    """

    def release(self) -> None: ...
    @property
    def released(self) -> bool: ...
    @property
    def sequence(self) -> int: ...
    def __enter__(self) -> Snapshot: ...
    def __exit__(self, *exc: object) -> bool: ...

class Iterator:
    """Cursor over a DB or transaction; invalidated when its parent ends.

    One thread at a time: do not close, release or end it from one thread
    while another thread is using it.
    """

    def close(self) -> None: ...
    @property
    def closed(self) -> bool: ...
    def __enter__(self) -> Iterator: ...
    def __exit__(self, *exc: object) -> bool: ...
    def seek(self, key: bytes) -> None: ...
    def seek_for_prev(self, key: bytes) -> None: ...
    def seek_to_first(self) -> None: ...
    def seek_to_last(self) -> None: ...
    def valid(self) -> bool: ...
    def key(self) -> bytes: ...
    def value(self) -> bytes: ...
    def item(self) -> tuple[bytes, bytes]: ...
    def next(self) -> None: ...
    def prev(self) -> None: ...
    def status(self) -> None: ...
    def __iter__(self) -> Iterator: ...
    def __next__(self) -> bytes | tuple[bytes, bytes]: ...
    def next_batch(self, n: int = 1000) -> list[bytes] | list[tuple[bytes, bytes]]: ...

class DB:
    path: str
    options: Options
    def __init__(
        self,
        path: StrPath,
        options: Options | None = None,
        *,
        read_only: bool = False,
        secondary_path: StrPath | None = None,
    ) -> None: ...
    def close(self) -> None:
        """Close the DB, invalidating its iterators and snapshots and rolling back
        open transactions. Raises RuntimeError while another thread is inside a
        call on this DB."""
    @property
    def closed(self) -> bool: ...
    def __enter__(self) -> DB: ...
    def __exit__(self, *exc: object) -> bool: ...
    def get(self, key: bytes, *, snapshot: Snapshot | None = None) -> bytes | None: ...
    def multi_get(
        self, keys: Iterable[bytes], *, snapshot: Snapshot | None = None
    ) -> list[bytes | None]: ...
    def snapshot(self) -> Snapshot: ...
    def iterator(
        self,
        *,
        snapshot: Snapshot | None = None,
        lower: bytes | None = None,
        upper: bytes | None = None,
        prefix: bytes | None = None,
        reverse: bool = False,
        keys_only: bool = False,
        fill_cache: bool = True,
    ) -> Iterator: ...
    @property
    def latest_sequence_number(self) -> int: ...
    def get_property(self, name: str | bytes) -> str | None: ...
    def put(self, key: bytes, value: bytes, *, sync: bool = False, disable_wal: bool = False) -> None: ...
    def delete(self, key: bytes, *, sync: bool = False, disable_wal: bool = False) -> None: ...
    def write(self, batch: WriteBatch, *, sync: bool = False, disable_wal: bool = False) -> None: ...
    def flush(self, *, wait: bool = True) -> None: ...
    def flush_wal(self, *, sync: bool = False) -> None: ...
    def compact_range(self, begin: bytes | None = None, end: bytes | None = None) -> None: ...
    def try_catch_up_with_primary(self) -> None: ...

class Transaction:
    """A transaction from TransactionDB.begin() or OptimisticTransactionDB.begin().

    One thread at a time: do not close, release or end it from one thread
    while another thread is using it.
    commit()/rollback() also invalidate its iterators and snapshot views.
    """

    optimistic: bool
    @property
    def active(self) -> bool: ...
    @property
    def committed(self) -> bool: ...
    @property
    def id(self) -> int: ...
    @property
    def num_keys(self) -> int: ...
    def __enter__(self) -> Transaction: ...
    def __exit__(self, *exc: object) -> bool: ...
    def set_snapshot(self) -> None: ...
    def clear_snapshot(self) -> None: ...
    @property
    def snapshot(self) -> Snapshot | None: ...
    def get(self, key: bytes, *, snapshot: Snapshot | None = None) -> bytes | None: ...
    def get_for_update(
        self,
        key: bytes,
        *,
        exclusive: bool = True,
        snapshot: Snapshot | None = None,
        validate: bool = True,
    ) -> bytes | None:
        """Read and lock (pessimistic) or track (optimistic) the key.

        validate=False reads latest and skips the conflict check; passing
        snapshot= with it raises ValueError.
        """
    def iterator(
        self,
        *,
        snapshot: Snapshot | None = None,
        lower: bytes | None = None,
        upper: bytes | None = None,
        prefix: bytes | None = None,
        reverse: bool = False,
        keys_only: bool = False,
        fill_cache: bool = True,
    ) -> Iterator: ...
    def put(self, key: bytes, value: bytes) -> None: ...
    def delete(self, key: bytes) -> None: ...
    def single_delete(self, key: bytes) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...

class TransactionDB(DB):
    def __init__(
        self,
        path: StrPath,
        options: Options | None = None,
        *,
        lock_timeout_ms: int = 1000,
        default_lock_timeout_ms: int = 1000,
        max_num_locks: int = -1,
        num_stripes: int = 16,
        max_num_deadlocks: int = 5,
    ) -> None: ...
    def begin(
        self,
        *,
        set_snapshot: bool = False,
        sync: bool = False,
        disable_wal: bool = False,
        lock_timeout_ms: int | None = None,
        deadlock_detect: bool = False,
        deadlock_detect_depth: int | None = None,
        expiration_ms: int | None = None,
    ) -> Transaction: ...

class OptimisticTransactionDB(DB):
    """Optimistic transactions: no locks, conflicts surface at commit as Busy.

    When options leave max_write_buffer_size_to_maintain at 0, memtable history
    of max_write_buffer_number * write_buffer_size is kept so commits after a
    flush still validate instead of raising TryAgain.
    """

    def __init__(
        self,
        path: StrPath,
        options: Options | None = None,
        *,
        validate_policy: Literal["parallel", "serial"] = "parallel",
        occ_lock_buckets: int | None = None,
    ) -> None: ...
    def begin(
        self, *, set_snapshot: bool = False, sync: bool = False, disable_wal: bool = False
    ) -> Transaction: ...
