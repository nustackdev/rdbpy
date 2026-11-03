# rdbpy

Python bindings for RocksDB 6.29.5, written in Cython. Small surface, every
read path takes a snapshot, every blocking call releases the GIL, every
RocksDB status maps to a typed exception.

**No RocksDB installation required**: wheels bundle RocksDB and the
compression libraries for Linux and macOS (Intel + Apple Silicon).

```bash
pip install rdbpython
```

## Usage

```python
import rdbpy

db = rdbpy.DB("/path/to/db", rdbpy.Options(create_if_missing=True, compression="lz4"))
db.put(b"k1", b"v1")
db.get(b"k1")            # b"v1"; None when missing
db.multi_get([b"k1", b"k2"])
db.delete(b"k1")

batch = rdbpy.WriteBatch()
batch.put(b"a", b"1")
batch.delete(b"b")
db.write(batch)

# snapshots: a point-in-time view accepted by every read
with db.snapshot() as snap:
    db.put(b"a", b"2")
    db.get(b"a", snapshot=snap)        # b"1"
    list(db.iterator(snapshot=snap))   # rows as of the snapshot

# iterators: bounds, prefix, direction, keys only, batched rows
for key, value in db.iterator(lower=b"a", upper=b"m"):
    ...
for key in db.iterator(prefix=b"user:", reverse=True, keys_only=True):
    ...
it = db.iterator()
while rows := it.next_batch(1000):   # one native loop per batch, not per row
    ...
it.seek(b"m"); it.valid(); it.key(); it.value(); it.next(); it.seek_for_prev(b"m")

db.close()
```

### Transactions

```python
db = rdbpy.TransactionDB(path, rdbpy.Options(create_if_missing=True), lock_timeout_ms=1000)

txn = db.begin(set_snapshot=True, deadlock_detect=True)
txn.get(b"a")                 # reads at the txn snapshot, merges own writes
txn.get_for_update(b"a")      # locks the row; Busy if it changed after the snapshot
txn.put(b"a", b"1")           # locks the row; TimedOut after lock_timeout_ms
txn.delete(b"b")
for k, v in txn.iterator(prefix=b"a"):
    ...
txn.commit()                  # or txn.rollback(); both end the transaction

odb = rdbpy.OptimisticTransactionDB(path)
txn = odb.begin()
txn.get_for_update(b"n")      # tracked read: commit fails with Busy if it changes
txn.put(b"n", b"1")
txn.commit()
```

Pessimistic (`TransactionDB`): `put`, `delete`, `get_for_update` take row locks
and raise `TimedOut` when the wait exceeds `lock_timeout_ms` (per DB or per
`begin`), `Deadlock` when `deadlock_detect=True` finds a cycle, `Busy` when a
key changed after the transaction's snapshot. Optimistic
(`OptimisticTransactionDB`): no locks, `commit()` raises `Busy` when a written
or tracked key changed. It keeps memtable history by default
(`max_write_buffer_size_to_maintain=0` becomes `-1`), so a commit after a flush
does not fail with `TryAgain`. `get_for_update(validate=False)` reads latest and
skips the check; combining it with `snapshot=` raises `ValueError`.

### Errors

All exceptions derive from `rdbpy.RocksDBError` (`.code`, `.subcode`,
`.message`). Transaction outcomes: `Busy`, `Deadlock` (a `Busy`), `TimedOut`,
`TryAgain`, `Expired`, `LockLimit`. Others: `Corruption`, `RocksIOError`,
`InvalidArgument`, `NotSupported`, `Incomplete`, `Aborted`, ... A missing key
is `None`, never an exception.

## Lifetimes and threads

Iterators, snapshots and transactions point into native state owned by their
parent:

- `Transaction.commit()` / `rollback()` end the transaction and invalidate
  every iterator and snapshot view created from it. A failed commit is rolled
  back.
- `DB.close()` invalidates every iterator and snapshot of the DB and rolls
  back any transaction still open.
- Using an invalidated object raises `RuntimeError`. Dropping one is safe, in
  any order, including when gc frees it.

Threads: rdbpy does no locking of its own and releases the GIL inside RocksDB
calls, so several threads can read and write the same DB concurrently (RocksDB
is thread safe). Child objects are different:

- `Snapshot`, `Iterator`, `Transaction` and `WriteBatch` are used by one thread
  at a time. Do not close, release, commit or roll back one from a thread while
  another thread is using it: that is a use after free.
- `DB.close()` raises `RuntimeError` while another thread is inside a call on
  the DB, so stop the workers before closing.

## Development

```bash
uv venv && uv pip install -e . pytest           # needs RDBPY_DEP_DIR, see below
RDBPY_DEP_DIR=~/opt/rocksdb-6.29.5 python setup.py build_ext --inplace
pytest tests
```

`RDBPY_DEP_DIR` points at a prefix with RocksDB 6.29.5 and the compression
libraries (`scripts/build-rocksdb-linux.sh` / `-macos.sh` build one). The
extension is linked with an rpath to `$RDBPY_DEP_DIR/lib`.

## License

Apache-2.0
