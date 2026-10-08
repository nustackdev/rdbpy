# rdbpy

Python bindings for RocksDB with Cython - **batteries included!**

**No RocksDB installation required** - everything is bundled in the wheel for Linux and macOS (Intel + Apple Silicon).

## Installation

```bash
pip install rdbpython
```

That's it! No need to install RocksDB or any compression libraries manually.

## Usage

```python
import rdbpy

# Open database
options = rdbpy.Options(create_if_missing=True)
db = rdbpy.DB('/path/to/db', options)

# Put/Get
db.put(b'key', b'value')
value = db.get(b'key')

# Iterate
it = db.iterkeys()
it.seek_to_first()
while it.valid():
    print(it.key())
    it.next()
```

## Lifetimes and threads

Iterators, snapshots and transactions point into native state owned by their parent:

- `Transaction.commit()`, `rollback()`, `close()` and a successful `rollback_to_save_point()` invalidate every iterator created from that transaction. So does `TransactionDB.begin_transaction(reuse=txn)`.
- `DB.close()` / `TransactionDB.close()` invalidate every iterator and snapshot of the DB and roll back any transaction that is still open.
- Using an invalidated iterator, or a DB after `close()`, raises `RuntimeError`. Dropping an invalidated object is safe, in any order, including when gc frees it.

Threads: a transaction and its iterators belong to one thread and must not be shared between threads. rdbpy does no locking of its own and releases the GIL inside RocksDB calls, so ending a transaction, or closing a DB, while another thread is still inside a call on it or on its iterators is undefined behaviour and can crash. Close a DB only after every thread is done with it. A finalizer (a generator's `finally`, `__del__`) that ends a transaction runs on whichever thread triggers gc, so it counts as using the transaction from that thread. gc merely freeing objects on another thread is safe.

## Development

```bash
# Setup
make install

# Build
make build

# Test
make test
```

## License

Apache-2.0
