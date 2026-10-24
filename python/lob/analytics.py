"""Market-microstructure and strategy-performance metrics (numpy only)."""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

import numpy as np


def _ffill(x: np.ndarray) -> np.ndarray:
    x = x.astype(float).copy()
    mask = np.isnan(x)
    if not mask.any():
        return x
    idx = np.where(~mask, np.arange(len(x)), 0)
    np.maximum.accumulate(idx, out=idx)
    return x[idx]


def order_flow_imbalance(bid_px, bid_qty, ask_px, ask_qty) -> np.ndarray:
    """Best-level order-flow imbalance (Cont, Kukanov & Stoikov 2014), one value per step (first is 0).

    e_n = 1{Pb_n >= Pb_{n-1}} qb_n - 1{Pb_n <= Pb_{n-1}} qb_{n-1}
        - 1{Pa_n <= Pa_{n-1}} qa_n + 1{Pa_n >= Pa_{n-1}} qa_{n-1}
    Positive OFI = net buying pressure.
    """
    bp, bq, ap, aq = (_ffill(np.asarray(a, dtype=float)) for a in (bid_px, bid_qty, ask_px, ask_qty))
    e = np.zeros(len(bp))
    if len(bp) < 2:
        return e
    bp0, bp1, bq0, bq1 = bp[:-1], bp[1:], bq[:-1], bq[1:]
    ap0, ap1, aq0, aq1 = ap[:-1], ap[1:], aq[:-1], aq[1:]
    e[1:] = ((bp1 >= bp0) * bq1 - (bp1 <= bp0) * bq0 - (ap1 <= ap0) * aq1 + (ap1 >= ap0) * aq0)
    return np.nan_to_num(e)


def ols(x: np.ndarray, y: np.ndarray) -> Dict[str, float]:
    """Simple regression y = a + b x. Returns slope, intercept, r2, t-stat of the slope, n."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    n = len(x)
    if n < 3 or np.std(x) == 0:
        return dict(slope=np.nan, intercept=np.nan, r2=np.nan, t=np.nan, n=n)
    b = np.cov(x, y, bias=True)[0, 1] / np.var(x)
    a = y.mean() - b * x.mean()
    resid = y - (a + b * x)
    ss_res, ss_tot = float(resid @ resid), float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    se_b = np.sqrt(ss_res / (n - 2) / (((x - x.mean()) ** 2).sum()))
    return dict(slope=float(b), intercept=float(a), r2=float(r2), t=float(b / se_b) if se_b > 0 else np.nan, n=n)


def acf(x: Sequence[float], nlags: int = 20) -> np.ndarray:
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    x = x - x.mean()
    denom = float(x @ x)
    if denom == 0:
        return np.zeros(nlags + 1)
    return np.array([1.0] + [float(x[k:] @ x[:-k]) / denom for k in range(1, nlags + 1)])


def realized_volatility(mid: Sequence[float], window: int = 100) -> np.ndarray:
    """Rolling std of per-step mid changes (ticks)."""
    d = np.diff(_ffill(np.asarray(mid, float)), prepend=np.nan)
    out = np.full(len(d), np.nan)
    for i in range(window, len(d)):
        out[i] = np.nanstd(d[i - window + 1:i + 1])
    return out


def max_drawdown(equity: Sequence[float]) -> float:
    e = np.asarray(equity, float)
    if len(e) == 0:
        return 0.0
    return float((np.maximum.accumulate(e) - e).max())


def strategy_report(pnl_rows: Sequence[tuple]) -> Dict[str, float]:
    """Summarise one strategy from rows (strategy, step, inventory, cash, mid, mtm_pnl)."""
    if not pnl_rows:
        return {}
    inv = np.array([r[2] for r in pnl_rows], float)
    mtm = np.array([r[5] for r in pnl_rows], float)
    d = np.diff(mtm)
    sd = d.std()
    return dict(
        final_pnl=float(mtm[-1]),
        max_drawdown=max_drawdown(mtm),
        inventory_sd=float(inv.std()),
        max_abs_inventory=float(np.abs(inv).max()),
        step_sharpe=float(d.mean() / sd) if sd > 0 else float("nan"),
        pnl_per_inventory_sd=float(mtm[-1] / inv.std()) if inv.std() > 0 else float("nan"),
    )


def impact_from_result(result) -> Dict[str, float]:
    """Regress next-step mid change on contemporaneous OFI: the 'price impact' slope in ticks per lot."""
    c = result.column
    e = order_flow_imbalance(c("best_bid"), c("bid_qty"), c("best_ask"), c("ask_qty"))
    dm = np.diff(_ffill(c("mid")), prepend=np.nan)
    return ols(e, dm)
