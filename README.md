# rdbpy

[![Build Wheels](https://github.com/everyabc/rdbpy/actions/workflows/build.yml/badge.svg)](https://github.com/everyabc/rdbpy/actions/workflows/build.yml)
[![Tests](https://github.com/everyabc/rdbpy/actions/workflows/test.yml/badge.svg)](https://github.com/everyabc/rdbpy/actions/workflows/test.yml)
[![PyPI version](https://badge.fury.io/py/rdbpython.svg)](https://pypi.org/project/rdbpython/)
[![Python Versions](https://img.shields.io/pypi/pyversions/rdbpython.svg)](https://pypi.org/project/rdbpython/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

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
