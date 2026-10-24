# Contributing

Issues and PRs are welcome. Good first areas: new order types (iceberg, stop), a LOBSTER/ITCH replay tool, more SQL analytics, new strategies.

```bash
make test        # C++ unit + differential tests
make pytest      # Python suite (builds the extension via `pip install -e .[dev]` first)
make sanitize    # ASan + UBSan
make mutation    # check that the tests catch injected bugs
```

Rules of the road
1. Any behaviour change to `OrderBook` must keep it **identical** to `ReferenceBook` (or change both deliberately, with a test explaining why).
2. Add a test that fails without your change. Tests must not use `assert` (it is compiled out in Release); use `CHECK`.
3. Prefer measured claims. If you say it is faster, add a workload to `benchmarks/bench.cpp`.
4. Keep Python and C++ semantics in lockstep: `python/tests/test_backends.py` will tell you if they drift.
