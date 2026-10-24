# Design

This document records *why* the engine looks the way it does, what was measured, and where it stops.

## 1. Data structures

| Concern | Choice | Complexity | Why |
|---|---|---|---|
| Price levels | Dense array per side, indexed by `price - min_price` | O(1) access | Prices are integer ticks in a bounded range, the standard approach in low-latency books. No tree walks, no pointer chasing, no per-level allocation. |
| Best bid / ask | Cached index + 64-bit **occupancy bitmap** | O(1) typical; O(range/64) worst case after the best level empties | `ctz`/`clz` over a word finds the next non-empty level in a few cycles. |
| Orders in a level | **Intrusive doubly-linked FIFO** (indices into a slab) | O(1) append, O(1) unlink | Price-time priority is just list order. Cancel never scans. |
| Order storage | Slab (`vector<Node>`) with a free list | O(1) alloc/free, no `malloc` on the hot path after warm-up | Slots are recycled; ids are not. |
| id → order | `vector<uint32_t>` indexed by id | O(1), no hashing | Ids are dense and sequential, so a hash map is unnecessary. |
| Timestamps | Logical clock (monotone counter) | - | Deterministic replays; wall-clock reads cost ~25 ns each and make runs non-reproducible. Callers may supply their own timestamp. |

**The baseline.** `ReferenceBook` (`include/lob/reference_book.hpp`) is the straightforward design,
`std::map<Price, std::deque>` plus a hash map, and has identical semantics. It serves as the
*oracle* for differential testing and as the *baseline* for benchmarks, so the speed-up is measured rather than claimed.

## 2. Matching semantics

| Order | Behaviour |
|---|---|
| Limit, GTC | Match while the opposite best price is at-or-better than the limit; rest any remainder at the limit price. |
| Limit, IOC | As GTC but the remainder is discarded. |
| Limit, FOK | Pre-checks available liquidity within the limit; fills completely or is rejected without touching the book. |
| Market | Matches at any price; never rests. Equivalent to IOC with an unbounded limit. |
| Post-only | Rejected (`PostOnlyWouldCross`) if it would take liquidity. Only valid with GTC. |
| Reduce | Lowers a resting order's size and **keeps** queue priority. |
| Replace | Cancel + new order: **loses** priority, gets a new id. Validated first, so a rejected replace leaves the original order intact. |

* Trade price is always the **resting** order's price.
* Every accepted order gets an id immediately, and **that same id** appears in its trades and is the one it rests under. (The first version used one id for trades and a different one for resting, which made fills impossible to attribute.)
* Rejected orders consume no id.

## 3. Invariants (checked by the tests)

1. The book is never crossed: `best_bid < best_ask` whenever both exist.
2. Within a price level, execution order equals arrival order, except that `reduce` keeps place and `replace` goes to the back.
3. `order_count()` equals the number of resting orders; level quantity equals the sum of its orders' remaining size.
4. For every accepted order: `quantity = filled + resting remainder + discarded remainder`.
5. `OrderBook` and `ReferenceBook` produce **identical** results (every `SubmitResult`, every trade, BBO, depth) for every operation in randomised streams, including invalid inputs, extreme prices and bitmap word boundaries.

## 4. Testing strategy

* **Unit tests** run against *both* implementations (`TEST_BOTH`).
* **Differential fuzzing**: ~1.1 M randomised operations per run across four regimes (tight band / deep book / tiny range spanning a bitmap word / offset price range), compared step by step against the reference.
* **Sanitizers**: the whole suite also runs under ASan + UBSan in CI.
* **Mutation check** (`scripts/mutation_check.sh`): injects known bugs (off-by-one in the price test, LIFO instead of FIFO, post-only check removed, ...) and requires the suite to *fail*.
* **No `assert`**: tests use a `CHECK` macro that survives `-DNDEBUG`. (The first version used `assert` in a Release build, i.e. its tests did nothing.)
* **Cross-language parity**: the pure-Python engine is verified against the C++ engine on random streams, and whole simulations are byte-identical across backends.

## 5. Python, SQL and R layers

```
C++ OrderBook ──pybind11──> lob (Python): simulator, strategies, analytics
                                  │ CSV / SQLite
                       ┌──────────┴──────────┐
                  lob/sql/*.sql            r/analyze.R
```

* The simulator logs every order, every trade and per-step top-of-book snapshots.
* The **same** price-impact regression is implemented in SQL (aggregate formulas over window-function output), NumPy, and R's `lm`, and the three agree. That is deliberate redundancy: it cross-validates the analytics.
* Market makers act only through the simulator gateway, so every order is logged and every fill is reconciled **from the trade tape by order id**, not guessed.

## 6. Known limitations (deliberate scope)

* **Bounded price range** (`min_price..max_price`, default 1..65,535, max ~4.2 M ticks). Orders outside it are rejected. Unbounded prices would need a sparse structure.
* **Single-threaded**, no locking. Matching engines are normally single-writer; concurrency lives around them.
* `slot_of_` grows 4 bytes per accepted order ever (ids are never reused); the optional trade tape grows without bound. Disable it with `set_record_tape(false)` for long runs.
* No self-trade prevention, iceberg/hidden orders, stop orders, auctions, or multiple instruments.
* No network protocol (FIX/ITCH), journaling or recovery.
* The simulator is a stylised model, not calibrated to any real market. Conclusions about strategies hold *inside the model*.

## 7. Next steps if you want to extend it

1. Replay real L3 data (e.g. LOBSTER) through `OrderBook` and validate against recorded trades.
2. Lock-free SPSC ring buffer in front of the engine (gateway thread to matching thread).
3. Hierarchical bitmap (two levels) to bound the worst-case best-price search.
4. Self-trade prevention + order-to-trade ratio limits.
5. Hawkes-process order flow for realistic clustering.
