"""Plain-Python value types shared by the pure-Python engine and the simulation layer.

The C++ extension exposes objects with the same attribute names, so user code never needs to know
which backend it is talking to.
"""

from __future__ import annotations

from enum import IntEnum
from typing import List, NamedTuple


try:  # one canonical set of enums per environment: the C++ ones if the extension is built
    from . import _core as _c

    Side, TimeInForce, RejectReason = _c.Side, _c.TimeInForce, _c.RejectReason
except ImportError:  # pragma: no cover - pure-Python install
    class Side(IntEnum):  # type: ignore[no-redef]
        Buy = 0
        Sell = 1

    class TimeInForce(IntEnum):  # type: ignore[no-redef]
        GTC = 0
        IOC = 1
        FOK = 2

    class RejectReason(IntEnum):  # type: ignore[no-redef]
        Accepted = 0
        InvalidQuantity = 1
        InvalidPrice = 2
        PriceOutOfRange = 3
        InvalidFlags = 4
        PostOnlyWouldCross = 5
        FokNotFillable = 6
        UnknownOrder = 7
        InvalidModify = 8


class Trade(NamedTuple):
    buy_order_id: int
    sell_order_id: int
    price: int
    quantity: int
    timestamp: int
    aggressor: int


class Level(NamedTuple):
    price: int
    quantity: int
    order_count: int


class OrderInfo(NamedTuple):
    id: int
    side: int
    price: int
    remaining: int


class SubmitResult:
    __slots__ = ("order_id", "trades", "filled", "remaining", "resting", "reject")

    def __init__(self, order_id: int = 0, trades: List[Trade] | None = None, filled: int = 0,
                 remaining: int = 0, resting: bool = False,
                 reject: RejectReason = RejectReason.Accepted):
        self.order_id = order_id
        self.trades = trades if trades is not None else []
        self.filled = filled
        self.remaining = remaining
        self.resting = resting
        self.reject = reject

    @property
    def accepted(self) -> bool:
        return int(self.reject) == 0

    def __repr__(self) -> str:
        return (f"SubmitResult(id={self.order_id}, filled={self.filled}, remaining={self.remaining}, "
                f"resting={self.resting}, reject={RejectReason(int(self.reject)).name})")
