"""Fixed-spread vs Avellaneda-Stoikov over many seeds (mean +/- standard error).

One run proves nothing in a stochastic simulation; this is how you should read the results.
"""

import sys

import numpy as np

from lob.analytics import strategy_report
from lob.simulator import MarketSimulator, SimConfig
from lob.strategies import AvellanedaStoikovMM, FixedSpreadMM

SEEDS = range(1, int(sys.argv[1]) + 1 if len(sys.argv) > 1 else 11)
CONTENDERS = {
    "fixed_spread  (half=3)": lambda: FixedSpreadMM(half_spread=3),
    "avellaneda_stoikov g=0.1": lambda: AvellanedaStoikovMM(gamma=0.1),
    "avellaneda_stoikov g=0.5": lambda: AvellanedaStoikovMM(gamma=0.5),
}

print(f"{'strategy':28s}{'PnL':>16s}{'inventory sd':>16s}{'max drawdown':>16s}{'PnL / inv-sd':>14s}")
for name, make in CONTENDERS.items():
    rows = []
    for seed in SEEDS:
        sim = MarketSimulator(SimConfig(n_steps=10_000, seed=seed))
        s = sim.add_strategy(make())
        sim.run()
        rows.append(strategy_report(sim.result.pnl))
    f = lambda k: (np.mean([r[k] for r in rows]), np.std([r[k] for r in rows], ddof=1) / np.sqrt(len(rows)))
    pnl, inv, dd, ratio = f("final_pnl"), f("inventory_sd"), f("max_drawdown"), f("pnl_per_inventory_sd")
    print(f"{name:28s}{pnl[0]:9.0f} ±{pnl[1]:4.0f}{inv[0]:10.1f} ±{inv[1]:4.1f}{dd[0]:10.0f} ±{dd[1]:4.0f}{ratio[0]:9.0f} ±{ratio[1]:3.0f}")
print(f"\n{len(list(SEEDS))} seeds x 10,000 steps each, separate simulation per run.")
