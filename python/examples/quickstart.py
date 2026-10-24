"""60-second tour of the order-book API."""

import lob
from lob import Side, TimeInForce

book = lob.OrderBook()                       # C++ engine if built, else pure Python
print("backend:", getattr(book, "backend", "cpp"))

book.limit(Side.Sell, 10_010, 8)
book.limit(Side.Sell, 10_015, 12)
book.limit(Side.Buy, 10_000, 10)
print("BBO:", book.best_bid(), "/", book.best_ask(), "| mid", book.mid_price(), "| spread", book.spread())

r = book.limit(Side.Buy, 10_015, 15, TimeInForce.IOC)           # sweeps two levels
print(r)
for t in r.trades:
    print("  trade", t.quantity, "@", t.price)

fok = book.limit(Side.Buy, 10_020, 100, TimeInForce.FOK)        # all-or-nothing
print("FOK:", fok.reject.name)

maker = book.limit(Side.Buy, 9_995, 5, post_only=True)          # rests, never takes liquidity
print("post-only rests:", maker.resting)
print("cancel:", book.cancel(maker.order_id))
print("depth:", [(l.price, l.quantity) for l in book.bid_levels(3)])
