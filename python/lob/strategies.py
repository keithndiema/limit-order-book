"""Market-making strategies.

Both strategies quote with **post-only** orders (they never take liquidity), reconcile fills from
the engine's trade tape by order id (so passive fills are accounted for), and are marked to the
mid price every step.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .types import Side


class Strategy:
    """Base class: inventory/cash accounting + two-sided quoting helper."""

    def __init__(self, name: str, size: int = 10, max_inventory: int = 200):
        self.name = name
        self.size = size
        self.max_inventory = max_inventory
        self.inventory = 0
        self.cash = 0.0                       # in tick-lots
        self.fill_count = 0
        self.traded_volume = 0
        self._ids: Dict[int, int] = {}        # live quote order id -> side
        self._bid_id: Optional[int] = None
        self._ask_id: Optional[int] = None
        self.last_row: Tuple = ()

    # -- fills (called by the simulator with every new trade) --------------------------
    def on_trades(self, trades, step: int) -> None:
        ids = self._ids
        for t in trades:
            if t.buy_order_id in ids:
                self.inventory += t.quantity
                self.cash -= t.price * t.quantity
                self.fill_count += 1
                self.traded_volume += t.quantity
            if t.sell_order_id in ids:
                self.inventory -= t.quantity
                self.cash += t.price * t.quantity
                self.fill_count += 1
                self.traded_volume += t.quantity

    def mark(self, step: int, mid: float) -> Tuple:
        mtm = self.cash + self.inventory * mid
        self.last_row = (step, self.inventory, self.cash, mid, mtm)
        return self.last_row

    # -- quoting helpers ---------------------------------------------------------------
    def _pull_quotes(self, sim) -> None:
        for oid in (self._bid_id, self._ask_id):
            if oid is not None:
                sim.cancel(self.name, oid)
                self._ids.pop(oid, None)
        self._bid_id = self._ask_id = None

    def _quote(self, sim, bid_px: int, ask_px: int) -> None:
        book = sim.book
        lo, hi = sim.cfg.min_price, sim.cfg.max_price
        ba, bb = book.best_ask(), book.best_bid()
        if ba is not None:
            bid_px = min(bid_px, ba - 1)                 # post-only: never cross
        if bb is not None:
            ask_px = max(ask_px, bb + 1)
        bid_px, ask_px = max(bid_px, lo), min(ask_px, hi)
        if self.inventory < self.max_inventory and bid_px >= lo:
            r = sim.place(self.name, Side.Buy, bid_px, self.size, post_only=True)
            if r.accepted:
                self._bid_id = r.order_id
                self._ids[r.order_id] = 0
        if self.inventory > -self.max_inventory and ask_px <= hi:
            r = sim.place(self.name, Side.Sell, ask_px, self.size, post_only=True)
            if r.accepted:
                self._ask_id = r.order_id
                self._ids[r.order_id] = 1

    def on_step(self, step: int, sim) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class FixedSpreadMM(Strategy):
    """Quotes mid +/- half_spread, shifted linearly against inventory. The honest baseline."""

    def __init__(self, half_spread: float = 3.0, skew_per_lot: float = 0.02, requote_every: int = 1,
                 size: int = 10, max_inventory: int = 200, name: str = "fixed_spread"):
        super().__init__(name, size, max_inventory)
        self.half_spread = half_spread
        self.skew_per_lot = skew_per_lot
        self.requote_every = requote_every

    def on_step(self, step: int, sim) -> None:
        if step % self.requote_every:
            return
        self._pull_quotes(sim)                 # read the book WITHOUT our own quotes in it
        mid = sim.book.mid_price()
        if mid is None:
            return
        shift = -self.skew_per_lot * self.inventory
        self._quote(sim, math.floor(mid + shift - self.half_spread), math.ceil(mid + shift + self.half_spread))


class AvellanedaStoikovMM(Strategy):
    """Avellaneda & Stoikov (2008) inventory-aware market maker, stationary-horizon form.

        reservation price   r     = s - q * gamma * sigma^2 * H
        optimal total spread delta = gamma * sigma^2 * H + (2 / gamma) * ln(1 + gamma / k)

    where s is the microprice, q the inventory in quote-sizes, sigma^2 an EWMA estimate of the
    per-step mid-price variance (ticks^2), H the (fixed) effective horizon in steps, gamma the risk
    aversion and k the decay of order-arrival intensity with distance from the mid.
    """

    def __init__(self, gamma: float = 0.1, k: float = 1.5, horizon: float = 10.0,
                 vol_halflife: float = 200.0, min_half_spread: float = 3.0, requote_every: int = 1,
                 size: int = 10, max_inventory: int = 200, name: str = "avellaneda_stoikov"):
        super().__init__(name, size, max_inventory)
        self.gamma, self.k, self.horizon = gamma, k, horizon
        self.min_half_spread = min_half_spread
        self.requote_every = requote_every
        self._alpha = 2.0 / (vol_halflife + 1.0)
        self._var = 1.0
        self._last_s: Optional[float] = None
        self.last_reservation: Optional[float] = None
        self.last_half_spread: Optional[float] = None

    def on_step(self, step: int, sim) -> None:
        if step % self.requote_every:
            return
        # Pull our quotes first: the reference price must come from the book *without* us in it,
        # otherwise the strategy anchors on its own quotes (a feedback loop that detaches the
        # mid from fundamental value).
        self._pull_quotes(sim)
        s = sim.book.microprice()
        if s is None:
            return
        if self._last_s is not None:
            d = s - self._last_s
            self._var = (1 - self._alpha) * self._var + self._alpha * d * d
        self._last_s = s

        q = self.inventory / self.size
        risk = self.gamma * self._var * self.horizon
        reservation = s - q * risk
        half = max(0.5 * (risk + (2.0 / self.gamma) * math.log(1.0 + self.gamma / self.k)),
                   self.min_half_spread)
        self.last_reservation, self.last_half_spread = reservation, half
        self._quote(sim, math.floor(reservation - half), math.ceil(reservation + half))
