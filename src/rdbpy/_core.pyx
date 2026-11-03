# distutils: language = c++
# cython: language_level=3
"""rdbpy core: a small Cython binding over RocksDB 6.29.5.

Shape: DB / TransactionDB / OptimisticTransactionDB, Transaction, Snapshot,
Iterator, WriteBatch, Options. Every read path takes a snapshot, every
blocking RocksDB call runs without the GIL, every non-ok status becomes a
typed exception (see rdbpy.errors).

Lifetime rules (iterators, snapshots, transactions point into native state
owned by their parent): a parent records each live child's address in a set
(an int, no reference cycle) and frees the children's native state before
its own. A child drops its entry when it is freed. Children are no_gc_clear
so they can still reach the parent in __dealloc__. Registries are walked
with set.pop() so no gc can run between taking an entry and freeing it.
"""
import cython
import os

from cpython.bytes cimport PyBytes_AS_STRING, PyBytes_GET_SIZE, PyBytes_FromStringAndSize
from libc.stddef cimport size_t
from libc.stdint cimport int64_t, uint32_t, uint64_t
from libcpp cimport bool as cpp_bool
from libcpp.string cimport string
from libcpp.vector cimport vector

cimport rdbpy._rocksdb as r

from rdbpy import errors


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

cdef inline size_t _addr(object ob):
    return <size_t><void*>ob


cdef inline r.Slice _slice(bytes b):
    return r.Slice(PyBytes_AS_STRING(b), <size_t>PyBytes_GET_SIZE(b))


cdef inline bytes _bytes(const r.Slice& s):
    return PyBytes_FromStringAndSize(s.data(), <Py_ssize_t>s.size())


cdef inline string _path(object path) except *:
    return <string>os.fsencode(path)


cdef inline int _check(const r.Status& st) except -1:
    if st.ok():
        return 0
    raise errors.error_for(
        r.status_code(st), r.status_subcode(st), st.ToString().decode("utf-8", "replace")
    )


cdef inline cpp_bool _is_not_found(const r.Status& st) nogil:
    return r.status_code(st) == 1


# In-flight native calls per DB. Taken with the GIL held around every
# `with nogil` block that touches the DB or its children, so close() can
# refuse instead of freeing state another thread is still inside.
cdef inline void _busy(DB db) noexcept:
    db._inflight += 1


cdef inline void _idle(DB db) noexcept:
    db._inflight -= 1


_COMPRESSION = {
    "none": r.kNoCompression,
    "snappy": r.kSnappyCompression,
    "zlib": r.kZlibCompression,
    "bz2": r.kBZip2Compression,
    "lz4": r.kLZ4Compression,
    "lz4hc": r.kLZ4HCCompression,
    "zstd": r.kZSTD,
}
_COMPRESSION_NAMES = {v: k for k, v in _COMPRESSION.items()}

_COMPACTION = {
    "level": r.kCompactionStyleLevel,
    "universal": r.kCompactionStyleUniversal,
    "fifo": r.kCompactionStyleFIFO,
}
_COMPACTION_NAMES = {v: k for k, v in _COMPACTION.items()}


def next_prefix(bytes prefix not None):
    """Smallest byte string greater than every string starting with `prefix`,
    or None when there is none (prefix empty or all 0xff)."""
    cdef bytearray b = bytearray(prefix)
    cdef Py_ssize_t n = len(b)
    while n > 0 and b[n - 1] == 0xFF:
        n -= 1
    if n == 0:
        return None
    del b[n:]
    b[n - 1] += 1
    return bytes(b)


# ----------------------------------------------------------------------------
# Options
# ----------------------------------------------------------------------------

cdef class Options:
    """DB options plus the block-based table options virtuals tunes.

    All fields are keyword arguments and read/write properties. Table-level
    fields (block_cache_size, block_size, bloom_bits_per_key, ...) build one
    BlockBasedTableFactory when the DB opens.
    """
    cdef r.Options opts
    cdef r.BlockBasedTableOptions bbto
    cdef bint bbto_set
    cdef double _bloom_bits
    cdef object _block_cache_size
    cdef size_t _prefix_len

    def __cinit__(self):
        self.bbto_set = False
        self._bloom_bits = 0.0
        self._block_cache_size = None
        self._prefix_len = 0

    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            if not hasattr(type(self), name):
                raise TypeError("unknown option %r" % name)
            setattr(self, name, value)

    cdef void _finalize(self) except *:
        if self.bbto_set:
            r.opts_set_table_factory(self.opts, self.bbto)

    # --- DBOptions ---
    @property
    def create_if_missing(self): return self.opts.create_if_missing
    @create_if_missing.setter
    def create_if_missing(self, bint v): self.opts.create_if_missing = v

    @property
    def error_if_exists(self): return self.opts.error_if_exists
    @error_if_exists.setter
    def error_if_exists(self, bint v): self.opts.error_if_exists = v

    @property
    def paranoid_checks(self): return self.opts.paranoid_checks
    @paranoid_checks.setter
    def paranoid_checks(self, bint v): self.opts.paranoid_checks = v

    @property
    def max_open_files(self): return self.opts.max_open_files
    @max_open_files.setter
    def max_open_files(self, int v): self.opts.max_open_files = v

    @property
    def use_fsync(self): return self.opts.use_fsync
    @use_fsync.setter
    def use_fsync(self, bint v): self.opts.use_fsync = v

    @property
    def wal_dir(self): return os.fsdecode(self.opts.wal_dir)
    @wal_dir.setter
    def wal_dir(self, v): self.opts.wal_dir = _path(v)

    @property
    def db_log_dir(self): return os.fsdecode(self.opts.db_log_dir)
    @db_log_dir.setter
    def db_log_dir(self, v): self.opts.db_log_dir = _path(v)

    @property
    def max_background_jobs(self): return self.opts.max_background_jobs
    @max_background_jobs.setter
    def max_background_jobs(self, int v): self.opts.max_background_jobs = v

    @property
    def max_log_file_size(self): return self.opts.max_log_file_size
    @max_log_file_size.setter
    def max_log_file_size(self, size_t v): self.opts.max_log_file_size = v

    @property
    def keep_log_file_num(self): return self.opts.keep_log_file_num
    @keep_log_file_num.setter
    def keep_log_file_num(self, size_t v): self.opts.keep_log_file_num = v

    @property
    def max_total_wal_size(self): return self.opts.max_total_wal_size
    @max_total_wal_size.setter
    def max_total_wal_size(self, uint64_t v): self.opts.max_total_wal_size = v

    @property
    def db_write_buffer_size(self): return self.opts.db_write_buffer_size
    @db_write_buffer_size.setter
    def db_write_buffer_size(self, size_t v): self.opts.db_write_buffer_size = v

    @property
    def allow_mmap_reads(self): return self.opts.allow_mmap_reads
    @allow_mmap_reads.setter
    def allow_mmap_reads(self, bint v): self.opts.allow_mmap_reads = v

    @property
    def allow_mmap_writes(self): return self.opts.allow_mmap_writes
    @allow_mmap_writes.setter
    def allow_mmap_writes(self, bint v): self.opts.allow_mmap_writes = v

    @property
    def use_direct_reads(self): return self.opts.use_direct_reads
    @use_direct_reads.setter
    def use_direct_reads(self, bint v): self.opts.use_direct_reads = v

    @property
    def use_direct_io_for_flush_and_compaction(self): return self.opts.use_direct_io_for_flush_and_compaction
    @use_direct_io_for_flush_and_compaction.setter
    def use_direct_io_for_flush_and_compaction(self, bint v): self.opts.use_direct_io_for_flush_and_compaction = v

    @property
    def bytes_per_sync(self): return self.opts.bytes_per_sync
    @bytes_per_sync.setter
    def bytes_per_sync(self, uint64_t v): self.opts.bytes_per_sync = v

    @property
    def wal_bytes_per_sync(self): return self.opts.wal_bytes_per_sync
    @wal_bytes_per_sync.setter
    def wal_bytes_per_sync(self, uint64_t v): self.opts.wal_bytes_per_sync = v

    @property
    def allow_concurrent_memtable_write(self): return self.opts.allow_concurrent_memtable_write
    @allow_concurrent_memtable_write.setter
    def allow_concurrent_memtable_write(self, bint v): self.opts.allow_concurrent_memtable_write = v

    @property
    def manual_wal_flush(self): return self.opts.manual_wal_flush
    @manual_wal_flush.setter
    def manual_wal_flush(self, bint v): self.opts.manual_wal_flush = v

    @property
    def avoid_unnecessary_blocking_io(self): return self.opts.avoid_unnecessary_blocking_io
    @avoid_unnecessary_blocking_io.setter
    def avoid_unnecessary_blocking_io(self, bint v): self.opts.avoid_unnecessary_blocking_io = v

    @property
    def atomic_flush(self): return self.opts.atomic_flush
    @atomic_flush.setter
    def atomic_flush(self, bint v): self.opts.atomic_flush = v

    @property
    def wal_ttl_seconds(self): return self.opts.WAL_ttl_seconds
    @wal_ttl_seconds.setter
    def wal_ttl_seconds(self, uint64_t v): self.opts.WAL_ttl_seconds = v

    @property
    def wal_size_limit_mb(self): return self.opts.WAL_size_limit_MB
    @wal_size_limit_mb.setter
    def wal_size_limit_mb(self, uint64_t v): self.opts.WAL_size_limit_MB = v

    # --- ColumnFamilyOptions ---
    @property
    def write_buffer_size(self): return self.opts.write_buffer_size
    @write_buffer_size.setter
    def write_buffer_size(self, size_t v): self.opts.write_buffer_size = v

    @property
    def max_write_buffer_number(self): return self.opts.max_write_buffer_number
    @max_write_buffer_number.setter
    def max_write_buffer_number(self, int v): self.opts.max_write_buffer_number = v

    @property
    def min_write_buffer_number_to_merge(self): return self.opts.min_write_buffer_number_to_merge
    @min_write_buffer_number_to_merge.setter
    def min_write_buffer_number_to_merge(self, int v): self.opts.min_write_buffer_number_to_merge = v

    @property
    def max_write_buffer_size_to_maintain(self): return self.opts.max_write_buffer_size_to_maintain
    @max_write_buffer_size_to_maintain.setter
    def max_write_buffer_size_to_maintain(self, int64_t v): self.opts.max_write_buffer_size_to_maintain = v

    @property
    def compression(self): return _COMPRESSION_NAMES.get(<int>self.opts.compression, "unknown")
    @compression.setter
    def compression(self, v):
        self.opts.compression = <r.CompressionType>_compression_value(v)

    @property
    def bottommost_compression(self): return _COMPRESSION_NAMES.get(<int>self.opts.bottommost_compression, "unknown")
    @bottommost_compression.setter
    def bottommost_compression(self, v):
        self.opts.bottommost_compression = <r.CompressionType>_compression_value(v)

    @property
    def num_levels(self): return self.opts.num_levels
    @num_levels.setter
    def num_levels(self, int v): self.opts.num_levels = v

    @property
    def level0_file_num_compaction_trigger(self): return self.opts.level0_file_num_compaction_trigger
    @level0_file_num_compaction_trigger.setter
    def level0_file_num_compaction_trigger(self, int v): self.opts.level0_file_num_compaction_trigger = v

    @property
    def level0_slowdown_writes_trigger(self): return self.opts.level0_slowdown_writes_trigger
    @level0_slowdown_writes_trigger.setter
    def level0_slowdown_writes_trigger(self, int v): self.opts.level0_slowdown_writes_trigger = v

    @property
    def level0_stop_writes_trigger(self): return self.opts.level0_stop_writes_trigger
    @level0_stop_writes_trigger.setter
    def level0_stop_writes_trigger(self, int v): self.opts.level0_stop_writes_trigger = v

    @property
    def target_file_size_base(self): return self.opts.target_file_size_base
    @target_file_size_base.setter
    def target_file_size_base(self, uint64_t v): self.opts.target_file_size_base = v

    @property
    def target_file_size_multiplier(self): return self.opts.target_file_size_multiplier
    @target_file_size_multiplier.setter
    def target_file_size_multiplier(self, int v): self.opts.target_file_size_multiplier = v

    @property
    def max_bytes_for_level_base(self): return self.opts.max_bytes_for_level_base
    @max_bytes_for_level_base.setter
    def max_bytes_for_level_base(self, uint64_t v): self.opts.max_bytes_for_level_base = v

    @property
    def max_bytes_for_level_multiplier(self): return self.opts.max_bytes_for_level_multiplier
    @max_bytes_for_level_multiplier.setter
    def max_bytes_for_level_multiplier(self, double v): self.opts.max_bytes_for_level_multiplier = v

    @property
    def level_compaction_dynamic_level_bytes(self): return self.opts.level_compaction_dynamic_level_bytes
    @level_compaction_dynamic_level_bytes.setter
    def level_compaction_dynamic_level_bytes(self, bint v): self.opts.level_compaction_dynamic_level_bytes = v

    @property
    def disable_auto_compactions(self): return self.opts.disable_auto_compactions
    @disable_auto_compactions.setter
    def disable_auto_compactions(self, bint v): self.opts.disable_auto_compactions = v

    @property
    def compaction_style(self): return _COMPACTION_NAMES.get(<int>self.opts.compaction_style, "unknown")
    @compaction_style.setter
    def compaction_style(self, v):
        if v not in _COMPACTION:
            raise ValueError("compaction_style must be one of %s" % sorted(_COMPACTION))
        self.opts.compaction_style = <r.CompactionStyle>(<int>_COMPACTION[v])

    @property
    def max_compaction_bytes(self): return self.opts.max_compaction_bytes
    @max_compaction_bytes.setter
    def max_compaction_bytes(self, uint64_t v): self.opts.max_compaction_bytes = v

    @property
    def optimize_filters_for_hits(self): return self.opts.optimize_filters_for_hits
    @optimize_filters_for_hits.setter
    def optimize_filters_for_hits(self, bint v): self.opts.optimize_filters_for_hits = v

    @property
    def memtable_prefix_bloom_size_ratio(self): return self.opts.memtable_prefix_bloom_size_ratio
    @memtable_prefix_bloom_size_ratio.setter
    def memtable_prefix_bloom_size_ratio(self, double v): self.opts.memtable_prefix_bloom_size_ratio = v

    @property
    def prefix_extractor_len(self):
        """Fixed-length prefix extractor (0 = none). Iterators always seek in
        total order, so this only feeds prefix bloom filters."""
        return self._prefix_len
    @prefix_extractor_len.setter
    def prefix_extractor_len(self, size_t v):
        self._prefix_len = v
        r.opts_set_prefix_extractor(self.opts, v)

    # --- BlockBasedTableOptions ---
    @property
    def block_cache_size(self):
        """LRU block cache capacity in bytes. None = rocksdb default (8MB)."""
        return self._block_cache_size
    @block_cache_size.setter
    def block_cache_size(self, v):
        self._block_cache_size = v
        self.bbto_set = True
        if v is None:
            self.bbto.no_block_cache = False
            r.bbto_set_cache(self.bbto, 8 << 20)
        elif int(v) <= 0:
            self.bbto.no_block_cache = True
        else:
            self.bbto.no_block_cache = False
            r.bbto_set_cache(self.bbto, <size_t>int(v))

    @property
    def block_size(self): return self.bbto.block_size
    @block_size.setter
    def block_size(self, size_t v):
        self.bbto_set = True
        self.bbto.block_size = v

    @property
    def block_restart_interval(self): return self.bbto.block_restart_interval
    @block_restart_interval.setter
    def block_restart_interval(self, int v):
        self.bbto_set = True
        self.bbto.block_restart_interval = v

    @property
    def bloom_bits_per_key(self): return self._bloom_bits
    @bloom_bits_per_key.setter
    def bloom_bits_per_key(self, double v):
        self.bbto_set = True
        self._bloom_bits = v
        r.bbto_set_bloom(self.bbto, v)

    @property
    def cache_index_and_filter_blocks(self): return self.bbto.cache_index_and_filter_blocks
    @cache_index_and_filter_blocks.setter
    def cache_index_and_filter_blocks(self, bint v):
        self.bbto_set = True
        self.bbto.cache_index_and_filter_blocks = v

    @property
    def pin_l0_filter_and_index_blocks_in_cache(self): return self.bbto.pin_l0_filter_and_index_blocks_in_cache
    @pin_l0_filter_and_index_blocks_in_cache.setter
    def pin_l0_filter_and_index_blocks_in_cache(self, bint v):
        self.bbto_set = True
        self.bbto.pin_l0_filter_and_index_blocks_in_cache = v

    @property
    def pin_top_level_index_and_filter(self): return self.bbto.pin_top_level_index_and_filter
    @pin_top_level_index_and_filter.setter
    def pin_top_level_index_and_filter(self, bint v):
        self.bbto_set = True
        self.bbto.pin_top_level_index_and_filter = v

    @property
    def partition_filters(self): return self.bbto.partition_filters
    @partition_filters.setter
    def partition_filters(self, bint v):
        self.bbto_set = True
        self.bbto.partition_filters = v

    @property
    def whole_key_filtering(self): return self.bbto.whole_key_filtering
    @whole_key_filtering.setter
    def whole_key_filtering(self, bint v):
        self.bbto_set = True
        self.bbto.whole_key_filtering = v

    @property
    def format_version(self): return self.bbto.format_version
    @format_version.setter
    def format_version(self, uint32_t v):
        self.bbto_set = True
        self.bbto.format_version = v

    @property
    def optimize_filters_for_memory(self): return self.bbto.optimize_filters_for_memory
    @optimize_filters_for_memory.setter
    def optimize_filters_for_memory(self, bint v):
        self.bbto_set = True
        self.bbto.optimize_filters_for_memory = v


cdef int _compression_value(v) except -1:
    if isinstance(v, str):
        if v not in _COMPRESSION:
            raise ValueError("compression must be one of %s" % sorted(_COMPRESSION))
        return <int>_COMPRESSION[v]
    return <int>v


# ----------------------------------------------------------------------------
# WriteBatch
# ----------------------------------------------------------------------------

cdef class WriteBatch:
    """Atomic group of puts and deletes, applied with DB.write()."""
    cdef r.WriteBatch* batch

    def __cinit__(self):
        self.batch = new r.WriteBatch()

    def __dealloc__(self):
        if self.batch != NULL:
            del self.batch
            self.batch = NULL

    def put(self, bytes key not None, bytes value not None):
        self.batch.Put(_slice(key), _slice(value))

    def delete(self, bytes key not None):
        self.batch.Delete(_slice(key))

    def single_delete(self, bytes key not None):
        self.batch.SingleDelete(_slice(key))

    def clear(self):
        self.batch.Clear()

    def count(self):
        return self.batch.Count()

    def __len__(self):
        return self.batch.Count()


# ----------------------------------------------------------------------------
# Snapshot
# ----------------------------------------------------------------------------

@cython.no_gc_clear
cdef class Snapshot:
    """A point-in-time view. Pass as `snapshot=` to any read.

    From DB.snapshot(): owned, release() (or the context manager, or gc) frees
    it. From Transaction.snapshot: a view on the transaction's own snapshot,
    valid until the transaction ends or changes snapshot.
    """
    cdef const r.Snapshot* ptr
    cdef DB db
    cdef set registry
    cdef bint owned

    def __cinit__(self, *args, **kwargs):
        self.ptr = NULL
        self.registry = None
        self.owned = False

    def __dealloc__(self):
        self._release()

    cdef void _release(self):
        cdef const r.Snapshot* p = self.ptr
        if p == NULL:
            return
        self.ptr = NULL
        if self.registry is not None:
            self.registry.discard(_addr(self))
        if self.owned and self.db is not None and self.db.db != NULL:
            _busy(self.db)
            with nogil:
                self.db.db.ReleaseSnapshot(p)
            _idle(self.db)

    cdef void _invalidate(self):
        # Called by the owner that is about to free the native snapshot.
        self.ptr = NULL

    cdef const r.Snapshot* _ptr(self, DB db) except NULL:
        if self.ptr == NULL:
            raise RuntimeError("snapshot has been released")
        if self.db is not db:
            raise ValueError("snapshot belongs to another DB")
        return self.ptr

    def release(self):
        """Free the native snapshot (no-op for transaction-owned views)."""
        self._release()

    @property
    def released(self):
        return self.ptr == NULL

    @property
    def sequence(self):
        if self.ptr == NULL:
            raise RuntimeError("snapshot has been released")
        return self.ptr.GetSequenceNumber()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._release()
        return False


cdef inline const r.Snapshot* _snap_ptr(object snapshot, DB db) except? NULL:
    if snapshot is None:
        return NULL
    if not isinstance(snapshot, Snapshot):
        raise TypeError("snapshot must be a Snapshot or None")
    return (<Snapshot>snapshot)._ptr(db)


# ----------------------------------------------------------------------------
# Iterator
# ----------------------------------------------------------------------------

@cython.no_gc_clear
cdef class Iterator:
    """Cursor over a DB or Transaction.

    Raw cursor methods: seek, seek_for_prev, seek_to_first, seek_to_last,
    valid, key, value, item, next, prev. Convenience: iteration (`for k, v in
    it`, or keys when keys_only) and next_batch(n), both walk in the direction
    given by `reverse` and position themselves on first use.

    Bounds (lower inclusive, upper exclusive) and prefix are passed to RocksDB
    and also enforced here: a transaction iterator's own pending writes are
    not bounded by RocksDB 6.29, so seeks are clamped into the window and a
    key outside it reads as invalid.
    """
    cdef r.Iterator* it
    cdef r.ReadOptions ro
    cdef r.Slice lower_s
    cdef r.Slice upper_s
    cdef bytes lower
    cdef bytes upper
    cdef bint has_lower
    cdef bint has_upper
    cdef DB db
    cdef set registry
    cdef bint reverse
    cdef bint keys_only
    cdef bint positioned

    def __cinit__(self, *args, **kwargs):
        self.it = NULL
        self.registry = None
        self.positioned = False
        self.has_lower = False
        self.has_upper = False

    def __dealloc__(self):
        self._free()

    cdef void _free(self):
        cdef r.Iterator* p = self.it
        if p == NULL:
            return
        self.it = NULL
        if self.registry is not None:
            self.registry.discard(_addr(self))
        # An iterator's destructor may drop the last SuperVersion ref and
        # purge obsolete files, so it runs without the GIL.
        with nogil:
            del p

    cdef void _invalidate(self):
        # Called by the parent, which already popped us from its registry.
        cdef r.Iterator* p = self.it
        if p == NULL:
            return
        self.it = NULL
        with nogil:
            del p

    cdef void _setup(self, DB db, set registry, const r.Snapshot* snap, lower, upper, prefix,
                     bint reverse, bint keys_only, bint fill_cache) except *:
        if prefix is not None:
            if lower is not None or upper is not None:
                raise ValueError("prefix cannot be combined with lower/upper")
            lower = prefix
            upper = next_prefix(prefix)
        self.db = db
        self.registry = registry
        self.reverse = reverse
        self.keys_only = keys_only
        self.ro.snapshot = snap
        self.ro.fill_cache = fill_cache
        self.ro.total_order_seek = True
        if lower is not None:
            self.lower = lower
            self.lower_s = _slice(self.lower)
            self.ro.iterate_lower_bound = &self.lower_s
            self.has_lower = True
        if upper is not None:
            self.upper = upper
            self.upper_s = _slice(self.upper)
            self.ro.iterate_upper_bound = &self.upper_s
            self.has_upper = True

    cdef inline int _check(self) except -1:
        if self.it == NULL or self.db.db == NULL:
            raise RuntimeError("iterator is closed or its parent has ended")
        return 0

    cdef inline int _status(self) except -1:
        cdef r.Status st
        _busy(self.db)
        try:
            with nogil:
                st = self.it.status()
        finally:
            _idle(self.db)
        return _check(st)

    # --- window-aware native moves (no GIL) ---
    cdef inline cpp_bool _valid(self) noexcept nogil:
        if not self.it.Valid():
            return False
        if self.has_upper and self.it.key().compare(self.upper_s) >= 0:
            return False
        if self.has_lower and self.it.key().compare(self.lower_s) < 0:
            return False
        return True

    cdef inline void _seek(self, const r.Slice& k) noexcept nogil:
        if self.has_lower and k.compare(self.lower_s) < 0:
            self.it.Seek(self.lower_s)
        else:
            self.it.Seek(k)

    cdef inline void _seek_first(self) noexcept nogil:
        if self.has_lower:
            self.it.Seek(self.lower_s)
        else:
            self.it.SeekToFirst()

    cdef inline void _seek_last(self) noexcept nogil:
        if self.has_upper:
            self.it.SeekForPrev(self.upper_s)
            while self.it.Valid() and self.it.key().compare(self.upper_s) >= 0:
                self.it.Prev()
        else:
            self.it.SeekToLast()

    cdef inline void _seek_for_prev(self, const r.Slice& k) noexcept nogil:
        if self.has_upper and k.compare(self.upper_s) >= 0:
            self._seek_last()
        else:
            self.it.SeekForPrev(k)

    def close(self):
        self._free()

    @property
    def closed(self):
        return self.it == NULL

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._free()
        return False

    # --- raw cursor ---
    def seek(self, bytes key not None):
        self._check()
        cdef r.Slice k = _slice(key)
        _busy(self.db)
        try:
            with nogil:
                self._seek(k)
        finally:
            _idle(self.db)
        self.positioned = True
        return self._status()

    def seek_for_prev(self, bytes key not None):
        self._check()
        cdef r.Slice k = _slice(key)
        _busy(self.db)
        try:
            with nogil:
                self._seek_for_prev(k)
        finally:
            _idle(self.db)
        self.positioned = True
        return self._status()

    def seek_to_first(self):
        self._check()
        _busy(self.db)
        try:
            with nogil:
                self._seek_first()
        finally:
            _idle(self.db)
        self.positioned = True
        return self._status()

    def seek_to_last(self):
        self._check()
        _busy(self.db)
        try:
            with nogil:
                self._seek_last()
        finally:
            _idle(self.db)
        self.positioned = True
        return self._status()

    def valid(self):
        self._check()
        return self._valid()

    def key(self):
        self._check()
        if not self._valid():
            raise RuntimeError("iterator is not valid")
        return _bytes(self.it.key())

    def value(self):
        self._check()
        if not self._valid():
            raise RuntimeError("iterator is not valid")
        return _bytes(self.it.value())

    def item(self):
        self._check()
        if not self._valid():
            raise RuntimeError("iterator is not valid")
        return (_bytes(self.it.key()), _bytes(self.it.value()))

    def next(self):
        self._check()
        _busy(self.db)
        try:
            with nogil:
                self.it.Next()
        finally:
            _idle(self.db)
        return self._status()

    def prev(self):
        self._check()
        _busy(self.db)
        try:
            with nogil:
                self.it.Prev()
        finally:
            _idle(self.db)
        return self._status()

    def status(self):
        """Raise the iterator's pending error, if any."""
        self._check()
        return self._status()

    # --- directional iteration ---
    cdef inline void _ensure_positioned(self) noexcept nogil:
        if not self.positioned:
            if self.reverse:
                self._seek_last()
            else:
                self._seek_first()
            self.positioned = True

    def __iter__(self):
        return self

    def __next__(self):
        self._check()
        cdef object out
        _busy(self.db)
        try:
            with nogil:
                self._ensure_positioned()
        finally:
            _idle(self.db)
        if not self._valid():
            self._status()
            raise StopIteration
        if self.keys_only:
            out = _bytes(self.it.key())
        else:
            out = (_bytes(self.it.key()), _bytes(self.it.value()))
        _busy(self.db)
        try:
            with nogil:
                if self.reverse:
                    self.it.Prev()
                else:
                    self.it.Next()
        finally:
            _idle(self.db)
        return out

    def next_batch(self, Py_ssize_t n=1000):
        """Up to n rows from the current position in the iteration direction,
        as a list of keys (keys_only) or (key, value) tuples. The native loop
        runs without the GIL; Python objects are built afterwards. An empty
        list means the end."""
        self._check()
        if n <= 0:
            raise ValueError("n must be positive")
        cdef vector[string] ks
        cdef vector[string] vs
        cdef Py_ssize_t left = n
        cdef bint keys_only = self.keys_only
        cdef bint reverse = self.reverse
        cdef r.Iterator* it = self.it
        _busy(self.db)
        try:
            with nogil:
                self._ensure_positioned()
                ks.reserve(<size_t>n)
                if not keys_only:
                    vs.reserve(<size_t>n)
                while left > 0 and self._valid():
                    ks.push_back(it.key().ToString())
                    if not keys_only:
                        vs.push_back(it.value().ToString())
                    if reverse:
                        it.Prev()
                    else:
                        it.Next()
                    left -= 1
        finally:
            _idle(self.db)
        if ks.empty():
            self._status()
            return []
        cdef size_t i, count = ks.size()
        cdef list out = [None] * <Py_ssize_t>count
        if keys_only:
            for i in range(count):
                out[i] = PyBytes_FromStringAndSize(ks[i].data(), <Py_ssize_t>ks[i].size())
        else:
            for i in range(count):
                out[i] = (
                    PyBytes_FromStringAndSize(ks[i].data(), <Py_ssize_t>ks[i].size()),
                    PyBytes_FromStringAndSize(vs[i].data(), <Py_ssize_t>vs[i].size()),
                )
        return out


cdef void _invalidate_iterators(set registry):
    cdef Iterator it
    if registry is None:
        return
    while registry:
        it = <Iterator><void*><size_t>registry.pop()
        it._invalidate()


cdef void _release_snapshots(set registry, r.DB* db):
    # DB close: owned snapshots must be released before the DB is deleted,
    # rocksdb does not free them itself.
    cdef Snapshot snap
    cdef const r.Snapshot* p
    if registry is None:
        return
    while registry:
        snap = <Snapshot><void*><size_t>registry.pop()
        p = snap.ptr
        snap._invalidate()
        if p != NULL and snap.owned:
            with nogil:
                db.ReleaseSnapshot(p)


cdef void _invalidate_snapshots(set registry):
    cdef Snapshot snap
    if registry is None:
        return
    while registry:
        snap = <Snapshot><void*><size_t>registry.pop()
        snap._invalidate()


# ----------------------------------------------------------------------------
# DB
# ----------------------------------------------------------------------------

@cython.no_gc_clear
cdef class DB:
    """A plain RocksDB handle.

    DB(path, options=None, *, read_only=False, secondary_path=None)

    read_only opens with OpenForReadOnly; secondary_path opens as a secondary
    instance that follows a primary (call try_catch_up_with_primary()).
    """
    cdef r.DB* db
    cdef set _iters
    cdef set _snaps
    cdef set _txns
    cdef int _inflight
    cdef readonly str path
    cdef readonly Options options

    def __cinit__(self, *args, **kwargs):
        self.db = NULL
        self._iters = set()
        self._snaps = set()
        self._txns = set()
        self._inflight = 0

    def __init__(self, path, Options options=None, *, bint read_only=False, secondary_path=None):
        cdef r.DB* db = NULL
        cdef r.Status st
        cdef string name = _path(path)
        cdef string secondary
        if options is None:
            options = Options(create_if_missing=True)
        options._finalize()
        self.path = os.fsdecode(path)
        self.options = options
        if secondary_path is not None:
            secondary = _path(secondary_path)
            with nogil:
                st = r.DB_OpenAsSecondary(options.opts, name, secondary, &db)
        elif read_only:
            with nogil:
                st = r.DB_OpenForReadOnly(options.opts, name, &db, False)
        else:
            with nogil:
                st = r.DB_Open(options.opts, name, &db)
        _check(st)
        self.db = db

    def __dealloc__(self):
        self._close()

    cdef void _close(self):
        cdef r.DB* p
        cdef Transaction txn
        if self.db == NULL:
            return
        # Detach first: from here every call on the DB or its children raises,
        # even while the steps below release the GIL.
        p = self.db
        self.db = NULL
        _invalidate_iterators(self._iters)
        _release_snapshots(self._snaps, p)
        while self._txns:
            txn = <Transaction><void*><size_t>self._txns.pop()
            txn._end(True)
        with nogil:
            del p

    cdef inline int _check(self) except -1:
        if self.db == NULL:
            raise RuntimeError("DB is closed")
        return 0

    def close(self):
        """Free every iterator, snapshot and transaction, then the DB.

        Raises RuntimeError while another thread is inside a call on this DB
        or one of its children (freeing it then would be a use after free).
        """
        if self._inflight:
            raise RuntimeError("DB is in use by another thread")
        self._close()

    @property
    def closed(self):
        return self.db == NULL

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __repr__(self):
        return "<%s %r%s>" % (type(self).__name__, self.path, " closed" if self.db == NULL else "")

    # --- reads ---
    def get(self, bytes key not None, *, snapshot=None):
        """Value for key at `snapshot` (or latest), None if missing."""
        self._check()
        cdef r.ReadOptions ro
        cdef r.Slice k = _slice(key)
        cdef string value
        cdef r.Status st
        ro.snapshot = _snap_ptr(snapshot, self)
        _busy(self)
        try:
            with nogil:
                st = r.db_get(self.db, ro, k, &value)
        finally:
            _idle(self)
        if _is_not_found(st):
            return None
        _check(st)
        return PyBytes_FromStringAndSize(value.data(), <Py_ssize_t>value.size())

    def multi_get(self, keys, *, snapshot=None):
        """Values for keys (list, None for missing) at `snapshot` or latest."""
        # Materialise first: iterating `keys` may run Python code (and let
        # another thread close the DB), so the closed check comes after.
        cdef list key_list = [k for k in keys]
        self._check()
        cdef r.ReadOptions ro
        cdef vector[r.Slice] ks
        cdef vector[string] vs
        cdef vector[r.Status] sts
        cdef size_t i, n = len(key_list)
        ro.snapshot = _snap_ptr(snapshot, self)
        ks.reserve(n)
        for k in key_list:
            if not isinstance(k, bytes):
                raise TypeError("keys must be bytes")
            ks.push_back(_slice(<bytes>k))
        _busy(self)
        try:
            with nogil:
                sts = self.db.MultiGet(ro, ks, &vs)
        finally:
            _idle(self)
        cdef list out = [None] * <Py_ssize_t>n
        for i in range(n):
            if _is_not_found(sts[i]):
                continue
            _check(sts[i])
            out[i] = PyBytes_FromStringAndSize(vs[i].data(), <Py_ssize_t>vs[i].size())
        return out

    def snapshot(self):
        """Take a snapshot of the current state (release it when done)."""
        self._check()
        cdef Snapshot snap = Snapshot.__new__(Snapshot)
        cdef const r.Snapshot* p
        _busy(self)
        try:
            with nogil:
                p = self.db.GetSnapshot()
        finally:
            _idle(self)
        snap.ptr = p
        snap.db = self
        snap.owned = True
        snap.registry = self._snaps
        self._snaps.add(_addr(snap))
        return snap

    def iterator(self, *, snapshot=None, lower=None, upper=None, prefix=None,
                 bint reverse=False, bint keys_only=False, bint fill_cache=True):
        """Cursor over [lower, upper) or `prefix`, at `snapshot` or latest."""
        self._check()
        cdef Iterator it = Iterator.__new__(Iterator)
        cdef r.Iterator* p
        it._setup(self, self._iters, _snap_ptr(snapshot, self), lower, upper, prefix,
                  reverse, keys_only, fill_cache)
        _busy(self)
        try:
            with nogil:
                p = self.db.NewIterator(it.ro)
        finally:
            _idle(self)
        it.it = p
        self._iters.add(_addr(it))
        return it

    @property
    def latest_sequence_number(self):
        self._check()
        return self.db.GetLatestSequenceNumber()

    def get_property(self, name):
        """A rocksdb.* property string, or None if unknown."""
        self._check()
        cdef bytes b = name.encode() if isinstance(name, str) else name
        cdef string out
        if not self.db.GetProperty(_slice(b), &out):
            return None
        return out.decode("utf-8", "replace")

    # --- writes ---
    def put(self, bytes key not None, bytes value not None, *, bint sync=False, bint disable_wal=False):
        self._check()
        cdef r.WriteOptions wo
        cdef r.Slice k = _slice(key)
        cdef r.Slice v = _slice(value)
        cdef r.Status st
        wo.sync = sync
        wo.disableWAL = disable_wal
        _busy(self)
        try:
            with nogil:
                st = self.db.Put(wo, k, v)
        finally:
            _idle(self)
        _check(st)

    def delete(self, bytes key not None, *, bint sync=False, bint disable_wal=False):
        self._check()
        cdef r.WriteOptions wo
        cdef r.Slice k = _slice(key)
        cdef r.Status st
        wo.sync = sync
        wo.disableWAL = disable_wal
        _busy(self)
        try:
            with nogil:
                st = self.db.Delete(wo, k)
        finally:
            _idle(self)
        _check(st)

    def write(self, WriteBatch batch not None, *, bint sync=False, bint disable_wal=False):
        """Apply a WriteBatch atomically."""
        self._check()
        cdef r.WriteOptions wo
        cdef r.Status st
        wo.sync = sync
        wo.disableWAL = disable_wal
        _busy(self)
        try:
            with nogil:
                st = self.db.Write(wo, batch.batch)
        finally:
            _idle(self)
        _check(st)

    # --- maintenance ---
    def flush(self, *, bint wait=True):
        self._check()
        cdef r.FlushOptions fo
        cdef r.Status st
        fo.wait = wait
        _busy(self)
        try:
            with nogil:
                st = self.db.Flush(fo)
        finally:
            _idle(self)
        _check(st)

    def flush_wal(self, *, bint sync=False):
        self._check()
        cdef r.Status st
        _busy(self)
        try:
            with nogil:
                st = self.db.FlushWAL(sync)
        finally:
            _idle(self)
        _check(st)

    def compact_range(self, bytes begin=None, bytes end=None):
        self._check()
        cdef r.CompactRangeOptions co
        cdef r.Slice b, e
        cdef const r.Slice* bp = NULL
        cdef const r.Slice* ep = NULL
        cdef r.Status st
        if begin is not None:
            b = _slice(begin)
            bp = &b
        if end is not None:
            e = _slice(end)
            ep = &e
        _busy(self)
        try:
            with nogil:
                st = self.db.CompactRange(co, bp, ep)
        finally:
            _idle(self)
        _check(st)

    def try_catch_up_with_primary(self):
        """Secondary instances: pull the primary's latest state."""
        self._check()
        cdef r.Status st
        _busy(self)
        try:
            with nogil:
                st = self.db.TryCatchUpWithPrimary()
        finally:
            _idle(self)
        _check(st)


# ----------------------------------------------------------------------------
# Transactions
# ----------------------------------------------------------------------------

@cython.no_gc_clear
cdef class Transaction:
    """A transaction from TransactionDB.begin() or OptimisticTransactionDB.begin().

    Reads default to the transaction's own snapshot when one is set (begin
    with set_snapshot=True, or set_snapshot()), and merge the transaction's
    pending writes. commit() and rollback() end it; a failed commit is rolled
    back. Use as a context manager to roll back on exceptions.
    """
    cdef r.Transaction* txn
    cdef DB db
    cdef set _iters
    cdef set _snaps
    cdef readonly bint optimistic
    cdef bint _committed

    def __cinit__(self, *args, **kwargs):
        self.txn = NULL
        self._iters = set()
        self._snaps = set()
        self._committed = False

    def __dealloc__(self):
        self._end(True)

    cdef void _end(self, bint rollback):
        # Free native state; rollback first when asked. Never raises.
        cdef r.Transaction* p = self.txn
        cdef r.Status st
        cdef DB db = self.db
        if p == NULL:
            return
        _invalidate_iterators(self._iters)
        _invalidate_snapshots(self._snaps)
        self.txn = NULL
        if self.db is not None and self.db._txns is not None:
            self.db._txns.discard(_addr(self))
        if db is not None:
            _busy(db)
        with nogil:
            if rollback:
                st = p.Rollback()
            del p
        if db is not None:
            _idle(db)

    cdef inline int _check(self) except -1:
        if self.txn == NULL:
            raise RuntimeError("transaction has ended")
        if self.db.db == NULL:
            raise RuntimeError("DB is closed")
        return 0

    cdef const r.Snapshot* _read_snapshot(self, object snapshot) except? NULL:
        if snapshot is None:
            return self.txn.GetSnapshot()
        return _snap_ptr(snapshot, self.db)

    @property
    def active(self):
        return self.txn != NULL

    @property
    def committed(self):
        return self._committed

    @property
    def id(self):
        self._check()
        return self.txn.GetID()

    @property
    def num_keys(self):
        self._check()
        return self.txn.GetNumKeys()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._end(True)
        return False

    # --- snapshot ---
    def set_snapshot(self):
        """Pin reads and conflict checks to the current state."""
        self._check()
        _invalidate_snapshots(self._snaps)
        _busy(self.db)
        try:
            with nogil:
                self.txn.SetSnapshot()
        finally:
            _idle(self.db)

    def clear_snapshot(self):
        self._check()
        _invalidate_snapshots(self._snaps)
        _busy(self.db)
        try:
            with nogil:
                self.txn.ClearSnapshot()
        finally:
            _idle(self.db)

    @property
    def snapshot(self):
        """The transaction's own snapshot (a view, not owned), or None."""
        self._check()
        cdef const r.Snapshot* p = self.txn.GetSnapshot()
        if p == NULL:
            return None
        cdef Snapshot snap = Snapshot.__new__(Snapshot)
        snap.ptr = p
        snap.db = self.db
        snap.owned = False
        snap.registry = self._snaps
        self._snaps.add(_addr(snap))
        return snap

    # --- reads ---
    def get(self, bytes key not None, *, snapshot=None):
        """Read, merging own writes. snapshot: None = the txn snapshot if set."""
        self._check()
        cdef r.ReadOptions ro
        cdef r.Slice k = _slice(key)
        cdef string value
        cdef r.Status st
        ro.snapshot = self._read_snapshot(snapshot)
        _busy(self.db)
        try:
            with nogil:
                st = r.txn_get(self.txn, ro, k, &value)
        finally:
            _idle(self.db)
        if _is_not_found(st):
            return None
        _check(st)
        return PyBytes_FromStringAndSize(value.data(), <Py_ssize_t>value.size())

    def get_for_update(self, bytes key not None, *, bint exclusive=True, snapshot=None,
                       bint validate=True):
        """Read and lock (pessimistic) or track (optimistic) the key.

        Conflict checks use the transaction's own snapshot: with one set and
        validate=True, raises Busy when the key changed after it (pessimistic)
        or fails the commit (optimistic). An explicit `snapshot=` only picks
        what is read. Lock waits raise TimedOut, cycles Deadlock.
        validate=False reads latest and skips the check; passing `snapshot=`
        with it raises ValueError.
        """
        self._check()
        cdef r.ReadOptions ro
        cdef r.Slice k = _slice(key)
        cdef string value
        cdef r.Status st
        if not validate and snapshot is not None:
            raise ValueError("snapshot cannot be combined with validate=False")
        ro.snapshot = self._read_snapshot(snapshot) if validate else NULL
        _busy(self.db)
        try:
            with nogil:
                st = r.txn_get_for_update(self.txn, ro, k, &value, exclusive, validate)
        finally:
            _idle(self.db)
        if _is_not_found(st):
            return None
        _check(st)
        return PyBytes_FromStringAndSize(value.data(), <Py_ssize_t>value.size())

    def iterator(self, *, snapshot=None, lower=None, upper=None, prefix=None,
                 bint reverse=False, bint keys_only=False, bint fill_cache=True):
        """Cursor merging own writes; snapshot defaults to the txn's."""
        self._check()
        cdef Iterator it = Iterator.__new__(Iterator)
        cdef r.Iterator* p
        it._setup(self.db, self._iters, self._read_snapshot(snapshot), lower, upper, prefix,
                  reverse, keys_only, fill_cache)
        _busy(self.db)
        try:
            with nogil:
                p = r.txn_iterator(self.txn, it.ro)
        finally:
            _idle(self.db)
        it.it = p
        self._iters.add(_addr(it))
        return it

    # --- writes ---
    def put(self, bytes key not None, bytes value not None):
        """Buffer a put; on a pessimistic DB this takes the key lock now."""
        self._check()
        cdef r.Slice k = _slice(key)
        cdef r.Slice v = _slice(value)
        cdef r.Status st
        _busy(self.db)
        try:
            with nogil:
                st = self.txn.Put(k, v)
        finally:
            _idle(self.db)
        _check(st)

    def delete(self, bytes key not None):
        self._check()
        cdef r.Slice k = _slice(key)
        cdef r.Status st
        _busy(self.db)
        try:
            with nogil:
                st = self.txn.Delete(k)
        finally:
            _idle(self.db)
        _check(st)

    def single_delete(self, bytes key not None):
        self._check()
        cdef r.Slice k = _slice(key)
        cdef r.Status st
        _busy(self.db)
        try:
            with nogil:
                st = self.txn.SingleDelete(k)
        finally:
            _idle(self.db)
        _check(st)

    # --- end ---
    def commit(self):
        """Commit and end. Raises Busy/TryAgain/Expired... and rolls back on failure."""
        self._check()
        cdef r.Transaction* p = self.txn
        cdef r.Status st
        _invalidate_iterators(self._iters)
        _invalidate_snapshots(self._snaps)
        _busy(self.db)
        try:
            with nogil:
                st = p.Commit()
        finally:
            _idle(self.db)
        if st.ok():
            self._committed = True
            self._end(False)
            return
        self._end(True)
        _check(st)

    def rollback(self):
        """Discard pending writes, release locks, end."""
        if self.txn == NULL:
            return
        self._end(True)


cdef Transaction _wrap_txn(DB db, r.Transaction* p, bint optimistic):
    cdef Transaction txn = Transaction.__new__(Transaction)
    txn.txn = p
    txn.db = db
    txn.optimistic = optimistic
    db._txns.add(_addr(txn))
    return txn


cdef class TransactionDB(DB):
    """Pessimistic transactions: writes and get_for_update take row locks.

    TransactionDB(path, options=None, *, lock_timeout_ms=1000,
                  default_lock_timeout_ms=1000, max_num_locks=-1,
                  num_stripes=16, max_num_deadlocks=5)

    lock_timeout_ms: per-lock wait for transactions (negative = no timeout).
    default_lock_timeout_ms: the same for plain db.put/delete/write.
    """

    def __init__(self, path, Options options=None, *, int64_t lock_timeout_ms=1000,
                 int64_t default_lock_timeout_ms=1000, int64_t max_num_locks=-1,
                 size_t num_stripes=16, uint32_t max_num_deadlocks=5):
        cdef r.TransactionDB* db = NULL
        cdef r.TransactionDBOptions tdo
        cdef r.Status st
        cdef string name = _path(path)
        if options is None:
            options = Options(create_if_missing=True)
        options._finalize()
        self.path = os.fsdecode(path)
        self.options = options
        tdo.transaction_lock_timeout = lock_timeout_ms
        tdo.default_lock_timeout = default_lock_timeout_ms
        tdo.max_num_locks = max_num_locks
        tdo.num_stripes = num_stripes
        tdo.max_num_deadlocks = max_num_deadlocks
        with nogil:
            st = r.TransactionDB_Open(options.opts, tdo, name, &db)
        _check(st)
        self.db = db

    def begin(self, *, bint set_snapshot=False, bint sync=False, bint disable_wal=False,
              lock_timeout_ms=None, bint deadlock_detect=False, deadlock_detect_depth=None,
              expiration_ms=None):
        """Start a transaction.

        lock_timeout_ms overrides the DB default for this transaction (0 =
        fail at once, negative = DB default). deadlock_detect makes lock waits
        raise Deadlock instead of timing out when they form a cycle.
        """
        self._check()
        cdef r.WriteOptions wo
        cdef r.TransactionOptions to
        cdef r.Transaction* p
        wo.sync = sync
        wo.disableWAL = disable_wal
        to.set_snapshot = set_snapshot
        to.deadlock_detect = deadlock_detect
        if lock_timeout_ms is not None:
            to.lock_timeout = <int64_t>lock_timeout_ms
        if deadlock_detect_depth is not None:
            to.deadlock_detect_depth = <int64_t>deadlock_detect_depth
        if expiration_ms is not None:
            to.expiration = <int64_t>expiration_ms
        _busy(self)
        try:
            with nogil:
                p = (<r.TransactionDB*>self.db).BeginTransaction(wo, to)
        finally:
            _idle(self)
        return _wrap_txn(self, p, False)


cdef class OptimisticTransactionDB(DB):
    """Optimistic transactions: no locks, conflicts surface at commit as Busy.

    OptimisticTransactionDB(path, options=None, *, validate_policy="parallel",
                            occ_lock_buckets=None)
    """

    def __init__(self, path, Options options=None, *, validate_policy="parallel",
                 occ_lock_buckets=None):
        cdef r.OptimisticTransactionDB* db = NULL
        cdef r.OptimisticTransactionDBOptions occ
        cdef r.Status st
        cdef string name = _path(path)
        if options is None:
            options = Options(create_if_missing=True)
        options._finalize()
        self.path = os.fsdecode(path)
        self.options = options
        if validate_policy == "parallel":
            occ.validate_policy = r.kValidateParallel
        elif validate_policy == "serial":
            occ.validate_policy = r.kValidateSerial
        else:
            raise ValueError("validate_policy must be 'parallel' or 'serial'")
        if occ_lock_buckets is not None:
            occ.occ_lock_buckets = <uint32_t>occ_lock_buckets
        with nogil:
            st = r.open_optimistic(options.opts, occ, name, &db)
        _check(st)
        self.db = db

    def begin(self, *, bint set_snapshot=False, bint sync=False, bint disable_wal=False):
        self._check()
        cdef r.WriteOptions wo
        cdef r.OptimisticTransactionOptions to
        cdef r.Transaction* p
        wo.sync = sync
        wo.disableWAL = disable_wal
        to.set_snapshot = set_snapshot
        _busy(self)
        try:
            with nogil:
                p = (<r.OptimisticTransactionDB*>self.db).BeginTransaction(wo, to)
        finally:
            _idle(self)
        return _wrap_txn(self, p, True)


# ----------------------------------------------------------------------------
# module functions
# ----------------------------------------------------------------------------

def destroy_db(path, Options options=None):
    """Delete a database directory's contents (the DB must be closed)."""
    cdef string name = _path(path)
    cdef r.Status st
    if options is None:
        options = Options()
    with nogil:
        st = r.DestroyDB(name, options.opts)
    _check(st)


def rocksdb_version():
    return "6.29.5"
