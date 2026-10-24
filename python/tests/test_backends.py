"""Semantics on every backend + randomised parity between the C++ and pure-Python engines."""

import random

import pytest

import lob
from lob import RejectReason, Side, TimeInForce

B, S = Side.Buy, Side.Sell


def test_price_time_priority_and_resting_price(book):
    first = book.limit(S, 100, 5)
    second = book.limit(S, 100, 5)
    better = book.limit(S, 99, 1)
    r = book.limit(B, 100, 7)
    assert [(t.sell_order_id, t.price, t.quantity) for t in r.trades] == [
        (better.order_id, 99, 1), (first.order_id, 100, 5), (second.order_id, 100, 1)]
    assert r.filled == 7 and not r.resting
    assert book.find_order(second.order_id).remaining == 4


def test_order_id_is_stable_between_trade_and_resting(book):
    book.limit(S, 100, 3)
    r = book.limit(B, 100, 10)
    assert r.resting and r.filled == 3 and r.remaining == 7
    assert r.trades[0].buy_order_id == r.order_id
    assert book.find_order(r.order_id).remaining == 7


def test_market_ioc_fok_postonly(book):
    book.limit(S, 100, 5)
    book.limit(S, 101, 5)
    assert book.limit(B, 101, 11, TimeInForce.FOK).reject == RejectReason.FokNotFillable
    assert book.total_trades() == 0
    assert book.limit(B, 100, 1, post_only=True).reject == RejectReason.PostOnlyWouldCross
    ioc = book.limit(B, 100, 9, TimeInForce.IOC)
    assert ioc.filled == 5 and ioc.remaining == 4 and not ioc.resting
    mkt = book.market(B, 50)
    assert mkt.filled == 5 and mkt.remaining == 45 and not mkt.resting
    assert book.best_ask() is None and book.best_bid() is None


def test_validation(backend):
    b = lob.OrderBook(10, 20, backend=backend)
    assert b.limit(B, 5, 1).reject == RejectReason.PriceOutOfRange
    assert b.limit(B, 0, 1).reject == RejectReason.InvalidPrice
    assert b.limit(B, 15, 0).reject == RejectReason.InvalidQuantity
    assert b.limit(B, 15, 1).accepted
    with pytest.raises(ValueError):
        lob.OrderBook(0, 10, backend=backend)


def test_cancel_reduce_replace(book):
    a = book.limit(B, 90, 10)
    c = book.limit(B, 90, 10)
    assert book.reduce(a.order_id, 4) == RejectReason.Accepted
    assert book.reduce(a.order_id, 4) == RejectReason.InvalidModify
    r = book.limit(S, 90, 4)
    assert r.trades[0].buy_order_id == a.order_id          # reduce kept priority
    rep = book.replace(c.order_id, 91, 3)
    assert rep.accepted and rep.resting and rep.order_id != c.order_id
    assert book.best_bid() == 91
    assert book.cancel(rep.order_id) and not book.cancel(rep.order_id)
    assert book.replace(12345, 90, 1).reject == RejectReason.UnknownOrder


def test_levels_and_microprice(book):
    book.limit(B, 100, 90)
    book.limit(B, 100, 10)
    book.limit(S, 102, 10)
    lv = book.bid_levels(1)[0]
    assert (lv.price, lv.quantity, lv.order_count) == (100, 100, 2)
    assert book.mid_price() == 101.0
    assert 101.0 < book.microprice() < 102.0
    assert book.spread() == 2


# ---------------------------------------------------------------------------------------------

def _norm(res):
    return (res.order_id, res.filled, res.remaining, bool(res.resting), int(res.reject),
            [(t.buy_order_id, t.sell_order_id, t.price, t.quantity, t.timestamp, int(t.aggressor)) for t in res.trades])


def _levels(lv):
    return [(l.price, l.quantity, l.order_count) for l in lv]


@pytest.mark.skipif(not lob.HAS_CPP, reason="C++ extension not built")
@pytest.mark.parametrize("seed", range(6))
def test_cpp_and_python_backends_agree(seed):
    rng = random.Random(seed)
    cpp, py = lob.OrderBook(1, 3000, backend="cpp"), lob.OrderBook(1, 3000, backend="python")
    ids = []
    for step in range(12000):
        side = B if rng.random() < 0.5 else S
        px = rng.randint(990, 1010)
        if rng.random() < 0.03:
            px = rng.choice([0, -1, 1, 3000, 3001])
        q = rng.randint(1, 30) if rng.random() > 0.02 else rng.randint(-1, 0)
        d = rng.random()
        if d < 0.45:
            ops = ("limit", (side, px, q))
        elif d < 0.55:
            ops = ("limit", (side, px, q, TimeInForce.IOC))
        elif d < 0.6:
            ops = ("limit", (side, px, q, TimeInForce.FOK))
        elif d < 0.66:
            ops = ("limit", (side, px, q, TimeInForce.GTC, True))
        elif d < 0.74:
            ops = ("market", (side, rng.randint(1, 60)))
        elif d < 0.9:
            ops = ("cancel", (rng.choice(ids) if ids and rng.random() > 0.05 else rng.randint(0, 99999),))
        elif d < 0.95 and ids:
            ops = ("reduce", (rng.choice(ids), rng.randint(-1, 25)))
        elif ids:
            ops = ("replace", (rng.choice(ids), px, q))
        else:
            continue
        name, args = ops
        a, b = getattr(cpp, name)(*args), getattr(py, name)(*args)
        if name in ("limit", "market", "replace"):
            assert _norm(a) == _norm(b), (step, ops)
            if a.accepted:
                ids.append(a.order_id)
        else:
            assert int(a) == int(b), (step, ops)
        assert cpp.best_bid() == py.best_bid() and cpp.best_ask() == py.best_ask()
        if step % 500 == 0:
            assert _levels(cpp.bid_levels(50)) == _levels(py.bid_levels(50))
            assert _levels(cpp.ask_levels(50)) == _levels(py.ask_levels(50))
            assert cpp.order_count() == py.order_count()
    assert cpp.total_volume() == py.total_volume() and cpp.total_trades() == py.total_trades()
    assert [(t.buy_order_id, t.sell_order_id, t.price, t.quantity, t.timestamp, int(t.aggressor))
            for t in cpp.trades_since(0)] == [tuple(map(int, t)) for t in py.trades_since(0)]
