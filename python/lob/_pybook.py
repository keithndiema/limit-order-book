"""Pure-Python limit order book with *exactly* the semantics of the C++ engine.

It exists so that (a) the whole toolkit runs without a compiler, and (b) the two backends can be
differentially tested against each other. It is O(1) for cancel (ordered dict per level) and
O(log n) for level insertion (bisect), so it is a respectable baseline rather than a strawman.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .types import (Level, OrderInfo, RejectReason, Side, SubmitResult, TimeInForce, Trade)

_BUY, _SELL = int(Side.Buy), int(Side.Sell)
_GTC, _IOC, _FOK = int(TimeInForce.GTC), int(TimeInForce.IOC), int(TimeInForce.FOK)
_OK = RejectReason.Accepted


class _Level:
    __slots__ = ("orders", "total")

    def __init__(self) -> None:
        self.orders: "OrderedDict[int, int]" = OrderedDict()   # order id -> remaining (FIFO)
        self.total = 0


class PyOrderBook:
    backend = "python"

    def __init__(self, min_price: int = 1, max_price: int = 65535):
        if min_price < 1 or max_price < min_price:
            raise ValueError("OrderBook: need 1 <= min_price <= max_price")
        self.min_price, self.max_price = int(min_price), int(max_price)
        self.reset()

    # -- lifecycle -------------------------------------------------------------------
    def reset(self) -> None:
        self._bids: Dict[int, _Level] = {}
        self._asks: Dict[int, _Level] = {}
        self._bid_px: List[int] = []        # ascending; best bid = last
        self._ask_px: List[int] = []        # stored NEGATED, ascending; best ask = -last
        self._index: Dict[int, Tuple[int, int]] = {}   # id -> (side, price) for resting orders
        self._tape: List[Trade] = []
        self._record_tape = True
        self._next_id = 1
        self._clock = 0
        self._total_trades = 0
        self._total_volume = 0

    def set_record_tape(self, on: bool) -> None:
        self._record_tape = bool(on)

    # -- order entry -----------------------------------------------------------------
    def limit(self, side, price: int, qty: int, tif=TimeInForce.GTC, post_only: bool = False) -> SubmitResult:
        return self._submit(int(side), False, int(price), int(qty), int(tif), bool(post_only))

    def market(self, side, qty: int) -> SubmitResult:
        return self._submit(int(side), True, 0, int(qty), _IOC, False)

    def _submit(self, side: int, is_market: bool, price: int, qty: int, tif: int, post_only: bool) -> SubmitResult:
        res = SubmitResult(remaining=qty)
        if qty <= 0:
            res.reject = RejectReason.InvalidQuantity
            return res
        buy = side == _BUY
        if is_market:
            limit = self.max_price if buy else self.min_price
        else:
            if price <= 0:
                res.reject = RejectReason.InvalidPrice
                return res
            if price < self.min_price or price > self.max_price:
                res.reject = RejectReason.PriceOutOfRange
                return res
            limit = price
        if post_only and tif != _GTC:
            res.reject = RejectReason.InvalidFlags
            return res
        if post_only and self._would_cross(side, limit):
            res.reject = RejectReason.PostOnlyWouldCross
            return res
        if tif == _FOK and self._available(side, limit, qty) < qty:
            res.reject = RejectReason.FokNotFillable
            return res

        oid = self._next_id
        self._next_id += 1
        self._clock += 1
        ts = self._clock
        res.order_id = oid
        remaining = self._match(side, limit, oid, ts, qty, res.trades)
        res.filled = qty - remaining
        res.remaining = remaining
        if remaining > 0 and tif == _GTC and not is_market:
            self._rest(side, limit, oid, remaining)
            res.resting = True
        return res

    def cancel(self, order_id: int) -> bool:
        loc = self._index.pop(order_id, None)
        if loc is None:
            return False
        side, price = loc
        book = self._bids if side == _BUY else self._asks
        lv = book[price]
        lv.total -= lv.orders.pop(order_id)
        if not lv.orders:
            self._drop_level(side, price)
        return True

    def reduce(self, order_id: int, new_qty: int) -> RejectReason:
        loc = self._index.get(order_id)
        if loc is None:
            return RejectReason.UnknownOrder
        side, price = loc
        lv = (self._bids if side == _BUY else self._asks)[price]
        cur = lv.orders[order_id]
        if new_qty <= 0 or new_qty >= cur:
            return RejectReason.InvalidModify
        lv.orders[order_id] = new_qty
        lv.total -= cur - new_qty
        return _OK

    def replace(self, order_id: int, price: int, qty: int) -> SubmitResult:
        res = SubmitResult(remaining=qty)
        loc = self._index.get(order_id)
        if loc is None:
            res.reject = RejectReason.UnknownOrder
        elif qty <= 0:
            res.reject = RejectReason.InvalidQuantity
        elif price <= 0:
            res.reject = RejectReason.InvalidPrice
        elif price < self.min_price or price > self.max_price:
            res.reject = RejectReason.PriceOutOfRange
        else:
            self.cancel(order_id)
            return self._submit(loc[0], False, int(price), int(qty), _GTC, False)
        return res

    # -- internals -------------------------------------------------------------------
    def _would_cross(self, side: int, price: int) -> bool:
        if side == _BUY:
            return bool(self._ask_px) and -self._ask_px[-1] <= price
        return bool(self._bid_px) and self._bid_px[-1] >= price

    def _available(self, side: int, limit: int, need: int) -> int:
        total = 0
        if side == _BUY:
            for neg in reversed(self._ask_px):
                if -neg > limit:
                    break
                total += self._asks[-neg].total
                if total >= need:
                    break
        else:
            for px in reversed(self._bid_px):
                if px < limit:
                    break
                total += self._bids[px].total
                if total >= need:
                    break
        return total

    def _match(self, side: int, limit: int, oid: int, ts: int, qty: int, out: List[Trade]) -> int:
        buy = side == _BUY
        remaining = qty
        book = self._asks if buy else self._bids
        px_list = self._ask_px if buy else self._bid_px
        while remaining > 0 and px_list:
            px = -px_list[-1] if buy else px_list[-1]
            if (px > limit) if buy else (px < limit):
                break
            lv = book[px]
            orders = lv.orders
            while remaining > 0 and orders:
                rid, rrem = next(iter(orders.items()))
                fill = rrem if rrem < remaining else remaining
                trade = Trade(oid if buy else rid, rid if buy else oid, px, fill, ts, side)
                out.append(trade)
                if self._record_tape:
                    self._tape.append(trade)
                remaining -= fill
                lv.total -= fill
                self._total_trades += 1
                self._total_volume += fill
                if fill == rrem:
                    del orders[rid]
                    del self._index[rid]
                else:
                    orders[rid] = rrem - fill
            if not orders:
                del book[px]
                px_list.pop()
        return remaining

    def _rest(self, side: int, price: int, oid: int, qty: int) -> None:
        book = self._bids if side == _BUY else self._asks
        lv = book.get(price)
        if lv is None:
            lv = book[price] = _Level()
            if side == _BUY:
                insort(self._bid_px, price)
            else:
                insort(self._ask_px, -price)
        lv.orders[oid] = qty
        lv.total += qty
        self._index[oid] = (side, price)

    def _drop_level(self, side: int, price: int) -> None:
        if side == _BUY:
            del self._bids[price]
            i = bisect_left(self._bid_px, price)
            del self._bid_px[i]
        else:
            del self._asks[price]
            i = bisect_left(self._ask_px, -price)
            del self._ask_px[i]

    # -- market data -----------------------------------------------------------------
    def best_bid(self) -> Optional[int]:
        return self._bid_px[-1] if self._bid_px else None

    def best_ask(self) -> Optional[int]:
        return -self._ask_px[-1] if self._ask_px else None

    def spread(self) -> Optional[int]:
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else a - b

    def mid_price(self) -> Optional[float]:
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else 0.5 * (b + a)

    def microprice(self) -> Optional[float]:
        b, a = self.best_bid(), self.best_ask()
        if b is None or a is None:
            return None
        bq, aq = self._bids[b].total, self._asks[a].total
        return (b * aq + a * bq) / (bq + aq)

    def bid_levels(self, n: int = 10) -> List[Level]:
        return [Level(p, self._bids[p].total, len(self._bids[p].orders)) for p in reversed(self._bid_px[-n:])] if n > 0 else []

    def ask_levels(self, n: int = 10) -> List[Level]:
        out = []
        for neg in reversed(self._ask_px[-n:] if n > 0 else []):
            p = -neg
            out.append(Level(p, self._asks[p].total, len(self._asks[p].orders)))
        return out

    def depth_at(self, side, price: int) -> int:
        lv = (self._bids if int(side) == _BUY else self._asks).get(price)
        return lv.total if lv else 0

    def find_order(self, order_id: int) -> Optional[OrderInfo]:
        loc = self._index.get(order_id)
        if loc is None:
            return None
        side, price = loc
        return OrderInfo(order_id, side, price, (self._bids if side == _BUY else self._asks)[price].orders[order_id])

    # -- statistics ------------------------------------------------------------------
    def order_count(self) -> int:
        return len(self._index)

    def total_trades(self) -> int:
        return self._total_trades

    def total_volume(self) -> int:
        return self._total_volume

    def trade_count(self) -> int:
        return len(self._tape)

    def trades_since(self, pos: int = 0) -> List[Trade]:
        return self._tape[pos:]
