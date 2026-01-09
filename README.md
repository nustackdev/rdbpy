# rdbpy

Python bindings for RocksDB with Cython.

## Installation

```bash
pip install rdbpy
```

## Usage

```python
import rocksdb

# Open database
options = rocksdb.Options(create_if_missing=True)
db = rocksdb.DB('/path/to/db', options)

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

MIT
