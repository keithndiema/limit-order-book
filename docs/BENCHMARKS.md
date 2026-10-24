# Benchmarks

Reproduce: `make bench` (writes `docs/assets/benchmark.{txt,json}`) then `python -c "from lob.viz import plot_benchmark; plot_benchmark('docs/assets/benchmark.json')"`.

## Method
* One pre-generated operation stream per workload (fixed seed), replayed identically against `OrderBook` and `ReferenceBook`.
* **Throughput**: median of 5 full replays of 2,000,000 operations; no timing calls inside the loop.
* **Latency**: separate replay with a `steady_clock` read around each operation; the median cost of an empty clock-read pair (26 ns here) is subtracted.
* Trade-tape recording off. Both implementations end each workload in the same state (checked by checksum; the benchmark aborts if they disagree).
* Mix: limit orders with exponentially distributed distance from a fixed reference price (8-10% cross the spread), market orders, and cancels of random *live* orders.

| Workload | Mean passive offset | Cancels | Market | What it stresses |
|---|---|---|---|---|
| tight | 4 ticks | 30% | 6% | very long FIFO queues per level |
| deep | 60 ticks | 30% | 6% | many levels, short queues |
| churn | 15 ticks | 40% | 4% | balanced insert / cancel |

## Results (2,000,000 ops each; single thread)

| Workload | OrderBook | ReferenceBook | Speed-up | OrderBook limit p50 / p99 | OrderBook cancel p50 / p99 |
|---|---|---|---|---|---|
| tight | 5.87 Mops/s | 0.25 Mops/s | 23x | 28 / 467 ns | 406 / 914 ns |
| deep  | 6.26 Mops/s | 1.41 Mops/s | 4.4x | 36 / 365 ns | 409 / 904 ns |
| churn | 10.54 Mops/s | 1.14 Mops/s | 9.2x | 28 / 310 ns | 256 / 806 ns |

Machine: 1 vCPU Intel Xeon @ 2.1 GHz (virtualised), g++ 13.3, `-O3 -march=native`.

## How to read these numbers (caveats)
* **The 23x is the baseline's worst case, not a typical speed-up.** With a mean offset of 4 ticks, queues hold thousands of orders, and the baseline's cancel is O(queue length) (p99 = 82 µs). The optimised book cancels in O(1). The *deep* workload (4.4x) is the fairer expectation when queues are short.
* **Books here grow to 200-500 k resting orders**, far deeper than a real book, because the synthetic flow has no inventory-balancing. That inflates cache misses: the ~400 ns cancel p50 is mostly a cache miss on a random node, not computation. Smaller books are faster.
* Throughput includes `live`-id bookkeeping done by the harness (identical for both books).
* A virtualised single core is noisy. Expect different absolute numbers on your machine; the *ratio* and the shape (O(1) vs O(queue)) are what to trust.
* This is a data-structure benchmark: no network, no persistence, no multi-threading. It says nothing about end-to-end exchange latency.
* Through the Python API the C++ backend is only ~1.6x faster than the pure-Python engine on `compare_backends.py`, because call overhead and the workload generator dominate. Use the C++ path directly (or batch) when speed matters.
