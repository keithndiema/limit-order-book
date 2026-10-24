import numpy as np
import pytest

from lob import store
from lob.analytics import impact_from_result
from lob.simulator import MarketSimulator, SimConfig
from lob.strategies import AvellanedaStoikovMM, FixedSpreadMM


@pytest.fixture(scope="module")
def run_and_db():
    sim = MarketSimulator(SimConfig(n_steps=5000, seed=11))
    sim.add_strategy(FixedSpreadMM())
    sim.add_strategy(AvellanedaStoikovMM())
    result = sim.run()
    con = store.write_sqlite(result, ":memory:")
    return sim, result, con


def q(con, name):
    cols, rows = store.run_query(con, name)
    return cols, rows


def test_every_bundled_query_runs(run_and_db):
    _, _, con = run_and_db
    names = store.available_queries()
    assert len(names) >= 8
    for n in names:
        cols, rows = q(con, n)
        assert cols and rows, n


def test_summary_matches_python(run_and_db):
    sim, result, con = run_and_db
    cols, rows = q(con, "01_summary")
    d = dict(zip(cols, rows[0]))
    assert d["steps"] == 5000
    assert d["trades"] == len(result.trades)
    assert d["volume"] == sim.book.total_volume()
    assert d["avg_spread_ticks"] == pytest.approx(np.nanmean(result.column("spread")), abs=1e-3)


def test_vwap_buckets_conserve_volume_and_vwap(run_and_db):
    _, result, con = run_and_db
    _, rows = q(con, "02_vwap_by_bucket")
    assert sum(r[6] for r in rows) == sum(t[5] for t in result.trades)
    first = [t for t in result.trades if t[1] < 1000]
    expected = sum(t[4] * t[5] for t in first) / sum(t[5] for t in first)
    assert rows[0][5] == pytest.approx(expected, abs=0.01)
    assert rows[0][3] <= rows[0][5] <= rows[0][2]       # low <= vwap <= high


def test_spread_distribution_is_a_proper_distribution(run_and_db):
    _, _, con = run_and_db
    _, rows = q(con, "03_spread_distribution")
    assert sum(r[2] for r in rows) == pytest.approx(100, abs=0.2)
    assert rows[-1][3] == pytest.approx(100, abs=0.01)
    cum = [r[3] for r in rows]
    assert cum == sorted(cum)


def test_sql_price_impact_matches_numpy_regression(run_and_db):
    _, result, con = run_and_db
    _, rows = q(con, "04_ofi_price_impact")
    py = impact_from_result(result)
    assert rows[0][1] == pytest.approx(py["slope"], abs=1e-5)
    assert rows[0][2] == pytest.approx(py["r2"], abs=1e-3)
    assert rows[0][1] > 0                      # buying pressure pushes the mid up


def test_markouts_match_independent_python_computation(run_and_db):
    _, result, con = run_and_db
    _, rows = q(con, "05_markouts")
    got = {(r[0], r[1]): r[3] for r in rows}
    mid = {s: m for s, m in zip(result.snapshots["step"], result.snapshots["mid"])}
    acc = {}
    for t in result.trades:
        step, price, agg = t[1], t[4], t[6]
        fut = mid.get(step + 10)
        if fut is None:
            continue
        owner, val = (t[8], price - fut) if agg == 0 else (t[7], fut - price)   # passive side's profit
        acc.setdefault(owner, []).append(val)
    for owner, vals in acc.items():
        assert got[(owner, 10)] == pytest.approx(np.mean(vals), abs=1e-3), owner


def test_pnl_attribution_reconciles(run_and_db):
    sim, _, con = run_and_db
    cols, rows = q(con, "06_strategy_pnl_attribution")
    for r in rows:
        d = dict(zip(cols, r))
        strat = next(s for s in sim.strategies if s.name == d["strategy"])
        assert d["total_pnl"] == pytest.approx(strat.last_row[4], abs=0.1)
        assert d["total_pnl"] == pytest.approx(d["spread_capture"] + d["inventory_pnl"], abs=0.2)
        assert d["final_inventory"] == strat.inventory


def test_trade_size_buckets_cover_everything(run_and_db):
    _, result, con = run_and_db
    _, rows = q(con, "08_trade_size_distribution")
    assert sum(r[1] for r in rows) == len(result.trades)
    assert sum(r[2] for r in rows) == pytest.approx(100, abs=0.1)
    assert sum(r[3] for r in rows) == pytest.approx(100, abs=0.1)


def test_foreign_key_and_constraints(run_and_db):
    _, _, con = run_and_db
    assert con.execute("SELECT COUNT(*) FROM trades t LEFT JOIN snapshots s ON s.step=t.step WHERE s.step IS NULL").fetchone()[0] == 0
    with pytest.raises(Exception):
        con.execute("INSERT INTO trades VALUES (999999, 0, 1, 2, 100, 0, 0, 'a', 'b')")   # quantity CHECK
