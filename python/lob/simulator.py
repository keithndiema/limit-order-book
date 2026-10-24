"""Agent-based order-flow simulator driving a real matching engine.

Market model (all quantities in integer ticks / lots):

* A latent *fundamental value* follows an Ornstein-Uhlenbeck process with rare jumps.
* **Noise traders** post limit orders around the fundamental with exponentially distributed
  distance (some land on the wrong side and cross), send market orders, and cancel at a constant
  hazard rate.
* A fraction of market orders is **informed**: they trade in the direction of (fundamental - mid).
  This creates adverse selection, the reason market makers cannot simply quote tight forever.
* **Strategies** (market makers) act through the simulator so every order and fill is logged and
  attributed; fills are reconciled from the engine's trade tape by order id.

Everything is seeded and deterministic, and the same seed produces identical results on the C++
and pure-Python backends.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .book import OrderBook
from .types import Side, TimeInForce

SNAPSHOT_COLUMNS = [
    "step", "fundamental", "best_bid", "bid_qty", "best_ask", "ask_qty", "mid", "microprice",
    "spread", "bid_depth5", "ask_depth5", "trades", "volume", "signed_volume", "resting_orders",
]
TRADE_COLUMNS = ["trade_id", "step", "buy_order_id", "sell_order_id", "price", "quantity",
                 "aggressor", "buyer_owner", "seller_owner"]
EVENT_COLUMNS = ["event_id", "step", "kind", "owner", "order_id", "side", "price", "quantity"]
PNL_COLUMNS = ["strategy", "step", "inventory", "cash", "mid", "mtm_pnl"]


@dataclass
class SimConfig:
    n_steps: int = 20_000
    seed: int = 42
    start_price: int = 10_000
    min_price: int = 1
    max_price: int = 65_535
    # latent fundamental value (ticks)
    ou_kappa: float = 0.01
    ou_sigma: float = 0.9
    jump_prob: float = 0.002
    jump_sigma: float = 8.0
    # noise order flow (per step)
    limit_rate: float = 1.4
    market_rate: float = 0.30
    cancel_hazard: float = 0.006        # per resting noise order per step
    offset_mean: float = 5.0            # mean passive distance in ticks
    qty_mean: float = 8.0
    informed_frac: float = 0.15
    warmup_orders: int = 60


class SimResult:
    """Container for everything a run produced (columnar for speed, convertible to pandas/CSV/SQL)."""

    def __init__(self, config: SimConfig, backend: str):
        self.config = config
        self.backend = backend
        self.snapshots: Dict[str, List[Any]] = {c: [] for c in SNAPSHOT_COLUMNS}
        self.trades: List[tuple] = []
        self.events: List[tuple] = []
        self.pnl: List[tuple] = []          # long format, one row per strategy per step
        self.strategies: List[Any] = []

    # -- conversions -----------------------------------------------------------------
    def column(self, name: str) -> np.ndarray:
        """Snapshot column as float array (None -> NaN)."""
        return np.array([np.nan if v is None else v for v in self.snapshots[name]], dtype=float)

    def to_frames(self):
        import pandas as pd  # optional dependency
        return {
            "snapshots": pd.DataFrame(self.snapshots),
            "trades": pd.DataFrame(self.trades, columns=TRADE_COLUMNS),
            "events": pd.DataFrame(self.events, columns=EVENT_COLUMNS),
            "pnl": pd.DataFrame(self.pnl, columns=PNL_COLUMNS),
        }

    def export_csv(self, out_dir: str = "results") -> Dict[str, Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = {}

        def dump(name, header, rows):
            p = out / f"{name}.csv"
            with open(p, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                for r in rows:
                    w.writerow(["" if v is None else v for v in r])
            paths[name] = p

        n = len(self.snapshots["step"])
        dump("snapshots", SNAPSHOT_COLUMNS, (tuple(self.snapshots[c][i] for c in SNAPSHOT_COLUMNS) for i in range(n)))
        dump("trades", TRADE_COLUMNS, self.trades)
        dump("events", EVENT_COLUMNS, self.events)
        dump("pnl", PNL_COLUMNS, self.pnl)
        return paths


class MarketSimulator:
    def __init__(self, config: Optional[SimConfig] = None, backend: str = "auto"):
        self.cfg = config or SimConfig()
        self.book = OrderBook(self.cfg.min_price, self.cfg.max_price, backend=backend)
        self.backend = getattr(self.book, "backend", "cpp")
        self.rng = np.random.default_rng(self.cfg.seed)
        self.strategies: List[Any] = []
        self.fundamental = float(self.cfg.start_price)
        self.step = 0
        self.result = SimResult(self.cfg, self.backend)
        self._owner: Dict[int, str] = {}
        self._live: List[int] = []            # resting noise orders (cancel candidates)
        self._tape_pos = 0
        self._event_id = 0
        self._trade_id = 0

    # ------------------------------------------------------------------ strategy gateway
    def add_strategy(self, strategy) -> Any:
        self.strategies.append(strategy)
        self.result.strategies.append(strategy)
        return strategy

    def place(self, owner: str, side, price: int, qty: int, post_only: bool = False,
              tif=TimeInForce.GTC):
        """Submit a limit order on behalf of `owner`; logs the event and records ownership."""
        res = self.book.limit(side, price, qty, tif, post_only)
        if res.accepted:
            self._owner[res.order_id] = owner
            self._log("LIMIT", owner, res.order_id, side, price, qty)
        return res

    def place_market(self, owner: str, side, qty: int):
        res = self.book.market(side, qty)
        if res.accepted:
            self._owner[res.order_id] = owner
            self._log("MARKET", owner, res.order_id, side, None, qty)
        return res

    def cancel(self, owner: str, order_id: int) -> bool:
        ok = self.book.cancel(order_id)
        if ok:
            self._log("CANCEL", owner, order_id, None, None, None)
        return ok

    def _log(self, kind, owner, order_id, side, price, qty):
        self._event_id += 1
        self.result.events.append((self._event_id, self.step, kind, owner, order_id,
                                   None if side is None else int(side), price, qty))

    # ------------------------------------------------------------------ market model
    def _mid(self) -> Optional[float]:
        return self.book.mid_price()

    def _qty(self, mean: float) -> int:
        return int(min(60, 1 + self.rng.geometric(1.0 / max(mean, 1.0)) - 1))

    def _noise_limit(self) -> None:
        c, rng = self.cfg, self.rng
        side = Side.Buy if rng.random() < 0.5 else Side.Sell
        d = rng.exponential(c.offset_mean) - 0.5
        px = self.fundamental - d if side == Side.Buy else self.fundamental + d
        px = int(min(max(round(px), c.min_price), c.max_price))
        res = self.place("noise", side, px, self._qty(c.qty_mean))
        if res.accepted and res.resting:
            self._live.append(res.order_id)

    def _noise_market(self) -> None:
        c, rng = self.cfg, self.rng
        owner = "noise"
        if rng.random() < c.informed_frac:
            mid = self._mid()
            edge = self.fundamental - (mid if mid is not None else self.fundamental)
            if abs(edge) >= 0.5:
                side = Side.Buy if edge > 0 else Side.Sell
                owner = "informed"
            else:
                side = Side.Buy if rng.random() < 0.5 else Side.Sell
        else:
            side = Side.Buy if rng.random() < 0.5 else Side.Sell
        self.place_market(owner, side, self._qty(c.qty_mean * 1.5))

    def _noise_cancels(self) -> None:
        if not self._live:
            return
        n = min(len(self._live), int(self.rng.poisson(self.cfg.cancel_hazard * len(self._live))))
        for _ in range(n):
            i = int(self.rng.integers(0, len(self._live)))
            oid = self._live[i]
            self._live[i] = self._live[-1]
            self._live.pop()
            self.cancel("noise", oid)          # may already be filled -> returns False, fine

    def _update_fundamental(self) -> None:
        c, rng = self.cfg, self.rng
        self.fundamental += -c.ou_kappa * (self.fundamental - c.start_price) + c.ou_sigma * rng.standard_normal()
        if rng.random() < c.jump_prob:
            self.fundamental += c.jump_sigma * rng.standard_normal()
        lo, hi = c.min_price + 50, c.max_price - 50
        self.fundamental = min(max(self.fundamental, lo), hi)

    def _warmup(self) -> None:
        c = self.cfg
        for i in range(c.warmup_orders):
            side = Side.Buy if i % 2 == 0 else Side.Sell
            d = 2 + (i // 2) % 25
            px = c.start_price - d if side == Side.Buy else c.start_price + d
            res = self.place("noise", side, px, self._qty(c.qty_mean))
            if res.accepted and res.resting:
                self._live.append(res.order_id)

    # ------------------------------------------------------------------ main loop
    def run(self, n_steps: Optional[int] = None) -> SimResult:
        c = self.cfg
        n = n_steps if n_steps is not None else c.n_steps
        if self.step == 0:
            self._warmup()
            self._tape_pos = self.book.trade_count()
        for _ in range(n):
            t = self.step
            self._update_fundamental()
            for s in self.strategies:
                s.on_step(t, self)

            n_lim = int(self.rng.poisson(c.limit_rate))
            n_mkt = int(self.rng.poisson(c.market_rate))
            kinds = [0] * n_lim + [1] * n_mkt
            if len(kinds) > 1:
                self.rng.shuffle(kinds)
            for k in kinds:
                self._noise_limit() if k == 0 else self._noise_market()
            self._noise_cancels()

            self._after_step(t)
            self.step += 1
        return self.result

    def _after_step(self, t: int) -> None:
        book = self.book
        new = book.trades_since(self._tape_pos)
        self._tape_pos += len(new)
        vol = sgn = 0
        for tr in new:
            self._trade_id += 1
            agg = int(tr.aggressor)
            self.result.trades.append((
                self._trade_id, t, tr.buy_order_id, tr.sell_order_id, tr.price, tr.quantity, agg,
                self._owner.get(tr.buy_order_id, "?"), self._owner.get(tr.sell_order_id, "?")))
            vol += tr.quantity
            sgn += tr.quantity if agg == 0 else -tr.quantity
        if new:
            for s in self.strategies:
                s.on_trades(new, t)

        bb, ba = book.best_bid(), book.best_ask()
        bl, al = book.bid_levels(5), book.ask_levels(5)
        snap = self.result.snapshots
        snap["step"].append(t)
        snap["fundamental"].append(round(self.fundamental, 4))
        snap["best_bid"].append(bb)
        snap["bid_qty"].append(bl[0].quantity if bl else None)
        snap["best_ask"].append(ba)
        snap["ask_qty"].append(al[0].quantity if al else None)
        snap["mid"].append(book.mid_price())
        snap["microprice"].append(book.microprice())
        snap["spread"].append(None if bb is None or ba is None else ba - bb)
        snap["bid_depth5"].append(sum(l.quantity for l in bl))
        snap["ask_depth5"].append(sum(l.quantity for l in al))
        snap["trades"].append(len(new))
        snap["volume"].append(vol)
        snap["signed_volume"].append(sgn)
        snap["resting_orders"].append(book.order_count())

        mid = book.mid_price()
        ref = mid if mid is not None else self.fundamental
        for s in self.strategies:
            row = s.mark(t, ref)
            self.result.pnl.append((s.name,) + row)
