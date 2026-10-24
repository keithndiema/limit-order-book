"""lob - a fast limit order book / matching engine with simulation, market making, SQL and R analytics."""

from .book import HAS_CPP, OrderBook
from .types import Level, OrderInfo, RejectReason, Side, SubmitResult, TimeInForce, Trade

__version__ = "1.0.0"

__all__ = [
    "OrderBook", "HAS_CPP", "Side", "TimeInForce", "RejectReason",
    "Trade", "Level", "OrderInfo", "SubmitResult", "__version__",
]
