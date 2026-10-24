"""Run every bundled SQL query against a fresh simulation."""

from lob.simulator import MarketSimulator, SimConfig
from lob.store import available_queries, format_table, run_query, write_sqlite
from lob.strategies import FixedSpreadMM

sim = MarketSimulator(SimConfig(n_steps=8_000, seed=5))
sim.add_strategy(FixedSpreadMM())
con = write_sqlite(sim.run(), ":memory:")
for name in available_queries():
    cols, rows = run_query(con, name)
    print(f"\n-- {name}\n{format_table(cols, rows, 8)}")
