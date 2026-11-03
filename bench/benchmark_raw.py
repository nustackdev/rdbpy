"""Raw rdbpy throughput: txn put/get, scans (per row and batched), batch write,
direct get. Run: python bench/benchmark_raw.py --num-keys 100000
"""

import argparse
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import rdbpy


def format_ops_per_sec(ops: int, elapsed: float) -> str:
    if elapsed <= 0:
        return "inf"
    rate = ops / elapsed
    if rate >= 1_000_000:
        return f"{rate / 1_000_000:.2f}M"
    if rate >= 1_000:
        return f"{rate / 1_000:.1f}K"
    return f"{rate:.0f}"


def benchmark(func: Callable[[], int]) -> tuple[float, int]:
    t0 = time.perf_counter()
    ops = func()
    return time.perf_counter() - t0, ops


def report(name: str, elapsed: float, ops: int) -> None:
    print(f"{name:<18}{elapsed:8.3f}s | {format_ops_per_sec(ops, elapsed):>10} ops/s")


def run_benchmarks(num_keys: int, value_size: int, db_path: Path) -> None:
    if db_path.exists():
        shutil.rmtree(db_path)
    db_path.mkdir(parents=True, exist_ok=True)

    db = rdbpy.TransactionDB(str(db_path), rdbpy.Options(create_if_missing=True))
    keys = [f"key:{i:08d}".encode() for i in range(num_keys)]
    value = b"x" * value_size

    print("\nBenchmark: raw rdbpy bindings")
    print(f"Keys: {num_keys:,}, Value size: {value_size} bytes")
    print("-" * 60)

    def bench_put() -> int:
        txn = db.begin()
        for key in keys:
            txn.put(key, value)
        txn.commit()
        return len(keys)

    report("put (txn)", *benchmark(bench_put))

    def bench_get() -> int:
        txn = db.begin()
        for key in keys:
            txn.get(key)
        txn.rollback()
        return len(keys)

    report("get (txn)", *benchmark(bench_get))

    def bench_get_for_update() -> int:
        txn = db.begin()
        for key in keys:
            txn.get_for_update(key)
        txn.rollback()
        return len(keys)

    report("get_for_update", *benchmark(bench_get_for_update))

    def bench_iter_keys() -> int:
        txn = db.begin()
        n = sum(1 for _ in txn.iterator(keys_only=True))
        txn.rollback()
        return n

    report("iter keys", *benchmark(bench_iter_keys))

    def bench_iter_items() -> int:
        n = sum(1 for _ in db.iterator())
        return n

    report("iter items", *benchmark(bench_iter_items))

    def bench_iter_batched() -> int:
        it = db.iterator()
        n = 0
        while True:
            rows = it.next_batch(1000)
            if not rows:
                break
            n += len(rows)
        return n

    report("iter next_batch", *benchmark(bench_iter_batched))

    def bench_snapshot_get() -> int:
        with db.snapshot() as snap:
            for key in keys:
                db.get(key, snapshot=snap)
        return len(keys)

    report("get (snapshot)", *benchmark(bench_snapshot_get))

    txn = db.begin()
    for key in keys:
        txn.delete(key)
    txn.commit()

    def bench_batch_put() -> int:
        batch = rdbpy.WriteBatch()
        for key in keys:
            batch.put(key, value)
        db.write(batch)
        return len(keys)

    report("batch put", *benchmark(bench_batch_put))

    def bench_direct_get() -> int:
        for key in keys:
            db.get(key)
        return len(keys)

    report("get (direct)", *benchmark(bench_direct_get))

    def bench_commits() -> int:
        n = min(num_keys, 10_000)
        for key in keys[:n]:
            txn = db.begin()
            txn.put(key, value)
            txn.commit()
        return n

    report("commit (1 put)", *benchmark(bench_commits))

    print("-" * 60)
    db.close()
    shutil.rmtree(db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark raw rdbpy bindings")
    parser.add_argument("--num-keys", type=int, default=100_000)
    parser.add_argument("--value-size", type=int, default=100)
    parser.add_argument("--db-path", type=Path, default=Path(".bench_rdbpy_raw"))
    args = parser.parse_args()
    run_benchmarks(args.num_keys, args.value_size, args.db_path)


if __name__ == "__main__":
    main()
