import numpy as np
import pytest

import lob
from lob.simulator import MarketSimulator, SimConfig
from lob.strategies import AvellanedaStoikovMM, FixedSpreadMM


def run(seed=3, steps=3000, backend="auto", strategies=(FixedSpreadMM, AvellanedaStoikovMM)):
    sim = MarketSimulator(SimConfig(n_steps=steps, seed=seed), backend=backend)
    for s in strategies:
        sim.add_strategy(s())
    sim.run()
    return sim


def test_deterministic_for_a_seed():
    a, b = run(), run()
    assert a.result.trades == b.result.trades
    assert a.result.events == b.result.events


@pytest.mark.skipif(not lob.HAS_CPP, reason="C++ extension not built")
def test_cpp_and_python_backends_produce_identical_runs():
    a, b = run(backend="cpp"), run(backend="python")
    assert a.result.trades == b.result.trades
    assert a.result.snapshots == b.result.snapshots
    assert a.result.pnl == b.result.pnl


def test_book_is_never_crossed_and_volume_reconciles():
    sim = run()
    r = sim.result
    bb, ba = r.column("best_bid"), r.column("best_ask")
    ok = ~(np.isnan(bb) | np.isnan(ba))
    assert ok.mean() > 0.99
    assert np.all(bb[ok] < ba[ok])
    assert sum(r.snapshots["volume"]) == sum(t[5] for t in r.trades) == sim.book.total_volume()


def test_strategy_accounting_matches_trade_table():
    """Inventory and cash tracked by the strategy must equal what the raw trade tape implies."""
    sim = run()
    for s in sim.strategies:
        inv = cash = 0
        for t in sim.result.trades:
            _, _, _, _, price, qty, _, buyer, seller = t
            if buyer == s.name:
                inv += qty; cash -= price * qty
            if seller == s.name:
                inv -= qty; cash += price * qty
        assert s.inventory == inv, s.name
        assert s.cash == pytest.approx(cash), s.name
        assert s.fill_count > 0


def test_market_makers_never_take_liquidity():
    sim = run()
    for t in sim.result.trades:
        agg_owner = t[7] if t[6] == 0 else t[8]
        assert agg_owner not in ("fixed_spread", "avellaneda_stoikov")


def test_avellaneda_stoikov_skews_quotes_against_inventory():
    sim = MarketSimulator(SimConfig(n_steps=50, seed=1))
    mm = sim.add_strategy(AvellanedaStoikovMM(gamma=0.5, horizon=20))
    sim.run(30)
    s_flat = sim.book  # reference only
    mm.inventory = 0
    mm.on_step(30, sim)
    flat_res = mm.last_reservation
    mm.inventory = 100
    mm.on_step(31, sim)
    long_res = mm.last_reservation
    mm.inventory = -100
    mm.on_step(32, sim)
    short_res = mm.last_reservation
    assert long_res < flat_res < short_res        # long -> quote lower to shed; short -> higher


def test_avellaneda_stoikov_reduces_inventory_risk_vs_fixed_spread():
    fixed_sd, as_sd = [], []
    for seed in range(1, 5):
        for cls, acc in ((FixedSpreadMM, fixed_sd), (AvellanedaStoikovMM, as_sd)):
            sim = run(seed=seed, steps=4000, strategies=(cls,))
            acc.append(np.std([r[2] for r in sim.result.pnl]))
    assert np.mean(as_sd) < np.mean(fixed_sd)


def test_informed_flow_creates_adverse_selection():
    """Passive fills should be followed by moves against the liquidity provider on average
    (markout below the half-spread it quoted)."""
    sim = run(steps=6000, strategies=(FixedSpreadMM,))
    mids = sim.result.column("mid")
    m = []
    for t in sim.result.trades:
        step, price, agg = t[1], t[4], t[6]
        if step + 10 < len(mids) and "fixed_spread" in (t[7], t[8]):
            passive_buy = agg == 1
            m.append((mids[step + 10] - price) if passive_buy else (price - mids[step + 10]))
    assert len(m) > 100
    assert np.mean(m) < 3.0       # strictly below the 3-tick half-spread it quotes


def test_csv_export_roundtrip(tmp_path):
    sim = run(steps=500)
    paths = sim.result.export_csv(str(tmp_path))
    assert set(paths) == {"snapshots", "trades", "events", "pnl"}
    assert sum(1 for _ in open(paths["snapshots"])) == 501
