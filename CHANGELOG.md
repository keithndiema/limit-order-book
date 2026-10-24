# Changelog

## 1.0.0

A ground-up rework of the original prototype. Honest list of what was wrong and what changed.

### Bugs fixed in the original
* **Tests were no-ops in Release.** They used `assert`, and the build set `-DNDEBUG`, so every "[PASS]" was vacuous. Replaced with an always-on `CHECK` harness; added a mutation check proving the suite can fail.
* **Passive fills were never accounted.** The market maker only recorded fills that happened while *it* submitted an order; fills when others hit its resting quotes (the whole point of market making) were dropped, so inventory and PnL were wrong. Fills are now reconciled from the trade tape by order id.
* **Order ids were inconsistent.** An aggressive order used one id in its trades and received a *different* id when its remainder rested. Now one id per order, for its whole life.
* The "mean-reverting" mid in the simulator was a clipped random walk; replaced with a real Ornstein-Uhlenbeck fundamental with jumps.
* `compare_backends.py` compared the same backend with itself. Backends can now be selected explicitly and are verified identical.
* Docs claimed ACF and microstructure metrics that were never implemented; unmeasured latency numbers were published. Removed, replaced with measured results.
* A self-referential bug introduced and caught during this rework: a maker computing its reference price from a book that contained its *own* quotes drifted away from fundamental value.

### New
* O(1) order book (dense level arrays, occupancy bitmap, intrusive FIFO, slab) ~3-13x faster than the `std::map` baseline.
* IOC, FOK, post-only, market, cancel, reduce (keeps priority), replace.
* Differential fuzzing against a reference book; ASan/UBSan; mutation check.
* pybind11 bindings + pure-Python engine with identical semantics (`pip install .`).
* Agent-based simulator (OU fundamental, noise + informed flow); fixed-spread and Avellaneda-Stoikov market makers.
* SQL layer (schema + 8 analytical queries incl. OFI price impact, markouts, PnL attribution) on SQLite.
* R analysis (base R) and cross-language agreement on price impact.
* CI, Dockerfile, Makefile, CLI (`lob demo`, `lob simulate`, `lob sql`, `lob_cli`).
