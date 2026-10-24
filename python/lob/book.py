"""Backend selection: compiled C++ engine when available, pure Python otherwise."""

from __future__ import annotations

from ._pybook import PyOrderBook

try:  # pragma: no cover - exercised by whichever build you have
    from . import _core
    HAS_CPP = True
except ImportError:  # pragma: no cover
    _core = None
    HAS_CPP = False


def OrderBook(min_price: int = 1, max_price: int = 65535, backend: str = "auto"):
    """Create an order book.

    backend: "auto" (C++ if built, else Python), "cpp", or "python".
    Both backends expose the same API and produce identical results (verified by the test-suite).
    """
    if backend not in ("auto", "cpp", "python"):
        raise ValueError("backend must be 'auto', 'cpp' or 'python'")
    if backend == "python" or (backend == "auto" and not HAS_CPP):
        return PyOrderBook(min_price, max_price)
    if not HAS_CPP:
        raise RuntimeError("C++ backend requested but the extension is not built: pip install .")
    book = _core.OrderBook(min_price, max_price)
    return book
