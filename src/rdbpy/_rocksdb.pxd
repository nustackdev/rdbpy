# Declarations of the RocksDB 6.29.5 C++ surface rdbpy uses. Nothing else.
from libc.stddef cimport size_t
from libc.stdint cimport int64_t, uint32_t, uint64_t
from libcpp cimport bool as cpp_bool
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "<memory>" namespace "std":
    cdef cppclass shared_ptr[T]:
        shared_ptr() except+ nogil
        shared_ptr(T*) except+ nogil
        void reset() except+ nogil
        void reset(T*) except+ nogil
        T* get() except+ nogil


cdef extern from "rocksdb/slice.h" namespace "rocksdb":
    cdef cppclass Slice:
        Slice() nogil
        Slice(const char*, size_t) nogil
        Slice(const string&) nogil
        const char* data() nogil
        size_t size() nogil
        int compare(const Slice&) nogil
        string ToString() nogil


cdef extern from "rocksdb/status.h" namespace "rocksdb":
    cdef cppclass Status:
        Status() nogil
        cpp_bool ok() nogil
        string ToString() except+ nogil


cdef extern from "rocksdb/snapshot.h" namespace "rocksdb":
    cdef cppclass Snapshot:
        uint64_t GetSequenceNumber() nogil


cdef extern from "rocksdb/cache.h" namespace "rocksdb":
    cdef cppclass Cache:
        pass
    shared_ptr[Cache] NewLRUCache(size_t capacity) except+ nogil


cdef extern from "rocksdb/filter_policy.h" namespace "rocksdb":
    cdef cppclass FilterPolicy:
        pass
    const FilterPolicy* NewBloomFilterPolicy(double bits_per_key, cpp_bool use_block_based_builder) except+ nogil


cdef extern from "rocksdb/slice_transform.h" namespace "rocksdb":
    cdef cppclass SliceTransform:
        pass
    const SliceTransform* NewFixedPrefixTransform(size_t prefix_len) except+ nogil


cdef extern from "rocksdb/table.h" namespace "rocksdb":
    cdef cppclass TableFactory:
        pass

    cdef cppclass BlockBasedTableOptions:
        BlockBasedTableOptions() except+ nogil
        cpp_bool no_block_cache
        size_t block_size
        int block_restart_interval
        cpp_bool cache_index_and_filter_blocks
        cpp_bool pin_l0_filter_and_index_blocks_in_cache
        cpp_bool pin_top_level_index_and_filter
        cpp_bool partition_filters
        cpp_bool whole_key_filtering
        uint32_t format_version
        cpp_bool optimize_filters_for_memory

    TableFactory* NewBlockBasedTableFactory(const BlockBasedTableOptions&) except+ nogil


cdef extern from "rocksdb/options.h" namespace "rocksdb":
    ctypedef enum CompressionType:
        kNoCompression
        kSnappyCompression
        kZlibCompression
        kBZip2Compression
        kLZ4Compression
        kLZ4HCCompression
        kZSTD

    ctypedef enum CompactionStyle:
        kCompactionStyleLevel
        kCompactionStyleUniversal
        kCompactionStyleFIFO

    cdef cppclass Options:
        Options() except+ nogil
        # DBOptions
        cpp_bool create_if_missing
        cpp_bool error_if_exists
        cpp_bool paranoid_checks
        int max_open_files
        cpp_bool use_fsync
        string db_log_dir
        string wal_dir
        int max_background_jobs
        size_t max_log_file_size
        size_t keep_log_file_num
        uint64_t max_total_wal_size
        size_t db_write_buffer_size
        cpp_bool allow_mmap_reads
        cpp_bool allow_mmap_writes
        cpp_bool use_direct_reads
        cpp_bool use_direct_io_for_flush_and_compaction
        uint64_t bytes_per_sync
        uint64_t wal_bytes_per_sync
        cpp_bool allow_concurrent_memtable_write
        cpp_bool manual_wal_flush
        cpp_bool avoid_unnecessary_blocking_io
        cpp_bool atomic_flush
        uint64_t WAL_ttl_seconds
        uint64_t WAL_size_limit_MB
        # ColumnFamilyOptions
        size_t write_buffer_size
        int max_write_buffer_number
        int min_write_buffer_number_to_merge
        int64_t max_write_buffer_size_to_maintain
        CompressionType compression
        CompressionType bottommost_compression
        int num_levels
        int level0_file_num_compaction_trigger
        int level0_slowdown_writes_trigger
        int level0_stop_writes_trigger
        uint64_t target_file_size_base
        int target_file_size_multiplier
        uint64_t max_bytes_for_level_base
        double max_bytes_for_level_multiplier
        cpp_bool level_compaction_dynamic_level_bytes
        cpp_bool disable_auto_compactions
        CompactionStyle compaction_style
        uint64_t max_compaction_bytes
        cpp_bool optimize_filters_for_hits
        double memtable_prefix_bloom_size_ratio

    cdef cppclass WriteOptions:
        WriteOptions() except+ nogil
        cpp_bool sync
        cpp_bool disableWAL
        cpp_bool no_slowdown

    cdef cppclass ReadOptions:
        ReadOptions() except+ nogil
        const Snapshot* snapshot
        const Slice* iterate_lower_bound
        const Slice* iterate_upper_bound
        cpp_bool verify_checksums
        cpp_bool fill_cache
        cpp_bool total_order_seek
        cpp_bool prefix_same_as_start

    cdef cppclass FlushOptions:
        FlushOptions() except+ nogil
        cpp_bool wait

    cdef cppclass CompactRangeOptions:
        CompactRangeOptions() except+ nogil


cdef extern from "rocksdb/iterator.h" namespace "rocksdb":
    cdef cppclass Iterator:
        cpp_bool Valid() except+ nogil
        void SeekToFirst() except+ nogil
        void SeekToLast() except+ nogil
        void Seek(const Slice&) except+ nogil
        void SeekForPrev(const Slice&) except+ nogil
        void Next() except+ nogil
        void Prev() except+ nogil
        Slice key() except+ nogil
        Slice value() except+ nogil
        Status status() except+ nogil


cdef extern from "rocksdb/write_batch.h" namespace "rocksdb":
    cdef cppclass WriteBatch:
        WriteBatch() except+ nogil
        void Put(const Slice&, const Slice&) except+ nogil
        void Delete(const Slice&, ) except+ nogil
        void SingleDelete(const Slice&) except+ nogil
        void Clear() except+ nogil
        int Count() except+ nogil


cdef extern from "rocksdb/db.h" namespace "rocksdb":
    cdef cppclass DB:
        Status Put(const WriteOptions&, const Slice&, const Slice&) except+ nogil
        Status Delete(const WriteOptions&, const Slice&) except+ nogil
        Status SingleDelete(const WriteOptions&, const Slice&) except+ nogil
        Status Write(const WriteOptions&, WriteBatch*) except+ nogil
        Status Get(const ReadOptions&, const Slice&, string*) except+ nogil
        vector[Status] MultiGet(const ReadOptions&, const vector[Slice]&, vector[string]*) except+ nogil
        Iterator* NewIterator(const ReadOptions&) except+ nogil
        const Snapshot* GetSnapshot() except+ nogil
        void ReleaseSnapshot(const Snapshot*) except+ nogil
        uint64_t GetLatestSequenceNumber() except+ nogil
        cpp_bool GetProperty(const Slice&, string*) except+ nogil
        Status Flush(const FlushOptions&) except+ nogil
        Status FlushWAL(cpp_bool sync) except+ nogil
        Status CompactRange(const CompactRangeOptions&, const Slice*, const Slice*) except+ nogil
        Status TryCatchUpWithPrimary() except+ nogil
        Status Close() except+ nogil

    Status DB_Open "rocksdb::DB::Open"(const Options&, const string&, DB**) except+ nogil
    Status DB_OpenForReadOnly "rocksdb::DB::OpenForReadOnly"(
        const Options&, const string&, DB**, cpp_bool error_if_wal_file_exists) except+ nogil
    Status DB_OpenAsSecondary "rocksdb::DB::OpenAsSecondary"(
        const Options&, const string&, const string&, DB**) except+ nogil
    Status DestroyDB(const string&, const Options&) except+ nogil


cdef extern from "rocksdb/utilities/transaction.h" namespace "rocksdb":
    cdef cppclass Transaction:
        Status Commit() except+ nogil
        Status Rollback() except+ nogil
        void SetSnapshot() except+ nogil
        const Snapshot* GetSnapshot() except+ nogil
        void ClearSnapshot() except+ nogil
        uint64_t GetID() except+ nogil
        Status Put(const Slice&, const Slice&) except+ nogil
        Status Delete(const Slice&) except+ nogil
        Status SingleDelete(const Slice&) except+ nogil
        Status Get(const ReadOptions&, const Slice&, string*) except+ nogil
        Status GetForUpdate(const ReadOptions&, const Slice&, string*, cpp_bool exclusive, cpp_bool do_validate) except+ nogil
        Iterator* GetIterator(const ReadOptions&) except+ nogil
        uint64_t GetNumKeys() except+ nogil


cdef extern from "rocksdb/utilities/transaction_db.h" namespace "rocksdb":
    cdef cppclass TransactionDBOptions:
        TransactionDBOptions() except+ nogil
        int64_t max_num_locks
        uint32_t max_num_deadlocks
        size_t num_stripes
        int64_t transaction_lock_timeout
        int64_t default_lock_timeout

    cdef cppclass TransactionOptions:
        TransactionOptions() except+ nogil
        cpp_bool set_snapshot
        cpp_bool deadlock_detect
        int64_t lock_timeout
        int64_t expiration
        int64_t deadlock_detect_depth
        size_t max_write_batch_size

    cdef cppclass TransactionDB(DB):
        Transaction* BeginTransaction(const WriteOptions&, const TransactionOptions&) except+ nogil

    Status TransactionDB_Open "rocksdb::TransactionDB::Open"(
        const Options&, const TransactionDBOptions&, const string&, TransactionDB**) except+ nogil


cdef extern from "rocksdb/utilities/optimistic_transaction_db.h" namespace "rocksdb":
    ctypedef enum OccValidationPolicy:
        kValidateSerial "rocksdb::OccValidationPolicy::kValidateSerial"
        kValidateParallel "rocksdb::OccValidationPolicy::kValidateParallel"

    cdef cppclass OptimisticTransactionOptions:
        OptimisticTransactionOptions() except+ nogil
        cpp_bool set_snapshot

    cdef cppclass OptimisticTransactionDBOptions:
        OptimisticTransactionDBOptions() except+ nogil
        OccValidationPolicy validate_policy
        uint32_t occ_lock_buckets

    cdef cppclass OptimisticTransactionDB(DB):
        Transaction* BeginTransaction(const WriteOptions&, const OptimisticTransactionOptions&) except+ nogil


# Small C++ helpers: status code access and overload disambiguation.
cdef extern from *:
    """
    #include <string>
    #include <vector>
    #include "rocksdb/db.h"
    #include "rocksdb/status.h"
    #include "rocksdb/utilities/transaction.h"
    #include "rocksdb/utilities/transaction_db.h"
    #include "rocksdb/utilities/optimistic_transaction_db.h"
    #include "rocksdb/table.h"
    #include "rocksdb/filter_policy.h"
    #include "rocksdb/slice_transform.h"
    #include "rocksdb/cache.h"

    namespace rdbpy {

    static inline int status_code(const rocksdb::Status& s) { return (int)s.code(); }
    static inline int status_subcode(const rocksdb::Status& s) { return (int)s.subcode(); }

    static inline rocksdb::Status txn_get(rocksdb::Transaction* txn,
                                          const rocksdb::ReadOptions& ro,
                                          const rocksdb::Slice& key,
                                          std::string* value) {
        return txn->Get(ro, key, value);
    }

    static inline rocksdb::Status txn_get_for_update(rocksdb::Transaction* txn,
                                                     const rocksdb::ReadOptions& ro,
                                                     const rocksdb::Slice& key,
                                                     std::string* value,
                                                     bool exclusive,
                                                     bool do_validate) {
        return txn->GetForUpdate(ro, key, value, exclusive, do_validate);
    }

    static inline rocksdb::Iterator* txn_iterator(rocksdb::Transaction* txn,
                                                  const rocksdb::ReadOptions& ro) {
        return txn->GetIterator(ro);
    }

    static inline rocksdb::Status db_get(rocksdb::DB* db,
                                         const rocksdb::ReadOptions& ro,
                                         const rocksdb::Slice& key,
                                         std::string* value) {
        return db->Get(ro, key, value);
    }

    static inline rocksdb::Status open_optimistic(const rocksdb::Options& opts,
                                                  const rocksdb::OptimisticTransactionDBOptions& occ,
                                                  const std::string& name,
                                                  rocksdb::OptimisticTransactionDB** out) {
        std::vector<rocksdb::ColumnFamilyDescriptor> cfs;
        cfs.emplace_back(rocksdb::kDefaultColumnFamilyName, rocksdb::ColumnFamilyOptions(opts));
        std::vector<rocksdb::ColumnFamilyHandle*> handles;
        rocksdb::Status s = rocksdb::OptimisticTransactionDB::Open(
            rocksdb::DBOptions(opts), occ, name, cfs, &handles, out);
        if (s.ok()) {
            // Handles returned by Open belong to the caller; the DB keeps its own
            // default handle, so these can go right away.
            for (auto* h : handles) delete h;
        }
        return s;
    }

    static inline void bbto_set_bloom(rocksdb::BlockBasedTableOptions& t, double bits) {
        if (bits > 0) t.filter_policy.reset(rocksdb::NewBloomFilterPolicy(bits, false));
        else t.filter_policy.reset();
    }
    static inline void bbto_set_cache(rocksdb::BlockBasedTableOptions& t, size_t bytes) {
        t.block_cache = rocksdb::NewLRUCache(bytes);
    }
    static inline void opts_set_table_factory(rocksdb::Options& o, const rocksdb::BlockBasedTableOptions& t) {
        o.table_factory.reset(rocksdb::NewBlockBasedTableFactory(t));
    }
    static inline void opts_set_prefix_extractor(rocksdb::Options& o, size_t n) {
        if (n > 0) o.prefix_extractor.reset(rocksdb::NewFixedPrefixTransform(n));
        else o.prefix_extractor.reset();
    }

    }  // namespace rdbpy
    """
    int status_code "rdbpy::status_code"(const Status&) nogil
    int status_subcode "rdbpy::status_subcode"(const Status&) nogil
    Status txn_get "rdbpy::txn_get"(Transaction*, const ReadOptions&, const Slice&, string*) except+ nogil
    Status txn_get_for_update "rdbpy::txn_get_for_update"(
        Transaction*, const ReadOptions&, const Slice&, string*, cpp_bool, cpp_bool) except+ nogil
    Iterator* txn_iterator "rdbpy::txn_iterator"(Transaction*, const ReadOptions&) except+ nogil
    Status db_get "rdbpy::db_get"(DB*, const ReadOptions&, const Slice&, string*) except+ nogil
    Status open_optimistic "rdbpy::open_optimistic"(
        const Options&, const OptimisticTransactionDBOptions&, const string&, OptimisticTransactionDB**) except+ nogil
    void bbto_set_bloom "rdbpy::bbto_set_bloom"(BlockBasedTableOptions&, double) except+ nogil
    void bbto_set_cache "rdbpy::bbto_set_cache"(BlockBasedTableOptions&, size_t) except+ nogil
    void opts_set_table_factory "rdbpy::opts_set_table_factory"(Options&, const BlockBasedTableOptions&) except+ nogil
    void opts_set_prefix_extractor "rdbpy::opts_set_prefix_extractor"(Options&, size_t) except+ nogil
