"""End-to-end: simulate -> CSV (for R) -> SQLite (for SQL) -> plots."""

from pathlib import Path

from lob.analytics import impact_from_result, strategy_report
from lob.simulator import MarketSimulator, SimConfig
from lob.store import available_queries, format_table, run_query, write_sqlite
from lob.strategies import AvellanedaStoikovMM, FixedSpreadMM
from lob.viz import plot_depth, plot_run

OUT = "results"

sim = MarketSimulator(SimConfig(n_steps=20_000, seed=42))
sim.add_strategy(FixedSpreadMM(half_spread=3))
sim.add_strategy(AvellanedaStoikovMM())
result = sim.run()
print(f"backend={sim.backend} trades={len(result.trades):,} events={len(result.events):,}")

for s in result.strategies:
    rep = strategy_report([r for r in result.pnl if r[0] == s.name])
    print(f"{s.name:20s}", {k: round(v, 2) for k, v in rep.items()})
print("price impact:", {k: round(v, 4) for k, v in impact_from_result(result).items()})

paths = result.export_csv(OUT)
con = write_sqlite(result, f"{OUT}/lob.sqlite")
for name in ("05_markouts", "06_strategy_pnl_attribution"):
    cols, rows = run_query(con, name)
    print(f"\n-- {name}\n{format_table(cols, rows)}")
print("\nplots:", plot_run(result, f"{OUT}/simulation.png"), plot_depth(sim.book, path=f"{OUT}/depth.png"))
print("next: Rscript r/analyze.R", OUT)
