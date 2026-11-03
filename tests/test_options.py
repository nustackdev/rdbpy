"""Options: kwargs, properties, table options, errors."""

import pytest

import rdbpy


def test_defaults_and_setters():
    o = rdbpy.Options()
    assert o.create_if_missing is False
    o.create_if_missing = True
    assert o.create_if_missing is True
    assert o.compression == "snappy"
    o.compression = "lz4"
    assert o.compression == "lz4"
    o.write_buffer_size = 1 << 20
    assert o.write_buffer_size == 1 << 20
    o.max_write_buffer_size_to_maintain = -1
    assert o.max_write_buffer_size_to_maintain == -1
    o.compaction_style = "universal"
    assert o.compaction_style == "universal"


def test_kwargs():
    o = rdbpy.Options(
        create_if_missing=True,
        paranoid_checks=False,
        max_open_files=100,
        max_background_jobs=2,
        write_buffer_size=4 << 20,
        max_write_buffer_number=3,
        level0_file_num_compaction_trigger=4,
        target_file_size_base=8 << 20,
        max_bytes_for_level_base=64 << 20,
        disable_auto_compactions=True,
        compression="none",
        bottommost_compression="zstd",
        block_cache_size=16 << 20,
        block_size=8192,
        bloom_bits_per_key=10,
        cache_index_and_filter_blocks=True,
        pin_l0_filter_and_index_blocks_in_cache=True,
        partition_filters=False,
        whole_key_filtering=True,
        format_version=5,
        prefix_extractor_len=4,
    )
    assert o.max_open_files == 100
    assert o.compression == "none"
    assert o.bottommost_compression == "zstd"
    assert o.block_cache_size == 16 << 20
    assert o.block_size == 8192
    assert o.bloom_bits_per_key == 10
    assert o.format_version == 5
    assert o.prefix_extractor_len == 4


def test_unknown_kwarg():
    with pytest.raises(TypeError):
        rdbpy.Options(no_such_option=1)


def test_bad_values():
    with pytest.raises(ValueError):
        rdbpy.Options(compression="brotli")
    with pytest.raises(ValueError):
        rdbpy.Options(compaction_style="zigzag")
    with pytest.raises((OverflowError, TypeError)):
        rdbpy.Options(write_buffer_size=-1)


def test_wal_dir(path):
    import os

    p = path()
    wal = p + "_wal"
    o = rdbpy.Options(create_if_missing=True, wal_dir=wal)
    assert o.wal_dir == wal
    with rdbpy.DB(p, o) as db:
        db.put(b"a", b"1")
    assert os.path.isdir(wal)


@pytest.mark.parametrize("compression", ["none", "snappy", "lz4", "zstd", "zlib", "bz2"])
def test_compression_roundtrip(path, compression):
    o = rdbpy.Options(create_if_missing=True, compression=compression)
    with rdbpy.DB(path(), o) as db:
        v = b"abc" * 10000
        db.put(b"a", v)
        db.flush()
        assert db.get(b"a") == v


def test_table_options_in_use(path):
    o = rdbpy.Options(
        create_if_missing=True,
        block_cache_size=1 << 20,
        bloom_bits_per_key=10,
        cache_index_and_filter_blocks=True,
        block_size=4096,
    )
    with rdbpy.DB(path(), o) as db:
        for i in range(1000):
            db.put(b"k%05d" % i, b"x" * 100)
        db.flush()
        assert db.get(b"k00500") == b"x" * 100
        assert db.get(b"missing") is None
        assert int(db.get_property("rocksdb.block-cache-usage")) > 0


def test_no_block_cache(path):
    o = rdbpy.Options(create_if_missing=True, block_cache_size=0)
    with rdbpy.DB(path(), o) as db:
        db.put(b"a", b"1")
        db.flush()
        assert db.get(b"a") == b"1"


def test_options_reusable_across_dbs(path):
    o = rdbpy.Options(create_if_missing=True, block_size=4096)
    with rdbpy.DB(path(), o) as a, rdbpy.DB(path(), o) as b:
        a.put(b"a", b"1")
        b.put(b"b", b"2")
        assert a.get(b"b") is None
        assert b.get(b"b") == b"2"
