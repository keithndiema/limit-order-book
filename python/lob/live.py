"""Live, read-only market data in the dashboard: public exchange order book + trades, no API keys, no orders sent.

    python -m lob.live                              # Kraken XBTUSD
    python -m lob.live --source coinbase --symbol ETH-USD
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.request
from collections import deque

from .web import HIST, LEVELS, _bind, _handler

INTERVAL = 1.5  # seconds between polls (stays well inside public rate limits)


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "lob-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


# ---------------------------------------------------------------------- Kraken
def _kraken_book(sym):
    d = _get(f"https://api.kraken.com/0/public/Depth?pair={sym}&count={LEVELS}")
    if d["error"]:
        raise RuntimeError(", ".join(d["error"]))
    b = next(iter(d["result"].values()))
    lv = lambda ls: [[float(x[0]), float(x[1]), 0] for x in ls]
    return lv(b["bids"]), lv(b["asks"])


def _kraken_trades(sym, cur):
    d = _get(f"https://api.kraken.com/0/public/Trades?pair={sym}" + (f"&since={cur}" if cur else ""))
    if d["error"]:
        raise RuntimeError(", ".join(d["error"]))
    rows = next(v for k, v in d["result"].items() if k != "last")
    if not cur:
        rows = rows[-20:]
    # side 'b' = buyer was the aggressor (0), 's' = seller (1)
    return [(time.strftime("%H:%M:%S", time.gmtime(float(r[2]))), float(r[0]), float(r[1]),
             0 if r[3] == "b" else 1) for r in rows], d["result"]["last"]


# ---------------------------------------------------------------------- Coinbase
def _cb_book(sym):
    d = _get(f"https://api.exchange.coinbase.com/products/{sym}/book?level=2")
    lv = lambda ls: [[float(x[0]), float(x[1]), int(x[2])] for x in ls[:LEVELS]]
    return lv(d["bids"]), lv(d["asks"])


def _cb_trades(sym, cur):
    rows = _get(f"https://api.exchange.coinbase.com/products/{sym}/trades")
    new = [r for r in rows if cur is None or r["trade_id"] > cur]
    if cur is None:
        new = new[:20]
    # Coinbase 'side' is the MAKER side: maker buy => the aggressor sold (1)
    out = [(r["time"][11:19], float(r["price"]), float(r["size"]), 1 if r["side"] == "buy" else 0)
           for r in reversed(new)]
    return out, max([r["trade_id"] for r in rows], default=cur)


FEEDS = {
    "kraken": {"book": _kraken_book, "trades": _kraken_trades, "symbol": "XBTUSD"},
    "coinbase": {"book": _cb_book, "trades": _cb_trades, "symbol": "BTC-USD"},
}


class LiveSession:
    """Same interface as web.Session (state/control/order/loop) so the existing server and UI are reused."""

    def __init__(self, source: str = "kraken", symbol: str | None = None):
        if source not in FEEDS:
            raise ValueError(f"source must be one of {tuple(FEEDS)}")
        self.source, self.symbol = source, symbol or FEEDS[source]["symbol"]
        self.lock = threading.RLock()
        self.running, self.n, self.cursor = True, 0, None
        self.bids, self.asks = [], []
        self.hist, self.tape = deque(maxlen=HIST), deque(maxlen=40)
        self.err, self.latency = None, None

    def poll(self) -> None:
        feed, t0 = FEEDS[self.source], time.time()
        try:
            bids, asks = feed["book"](self.symbol)
        except Exception as e:  # network / API errors must never kill the poller
            with self.lock:
                self.err = f"{type(e).__name__}: {e}"[:140]
            return
        err, trades, cur = None, [], self.cursor
        try:
            trades, cur = feed["trades"](self.symbol, self.cursor)
        except Exception as e:
            err = f"trades: {type(e).__name__}: {e}"[:140]
        with self.lock:
            self.err, self.cursor, self.latency = err, cur, int((time.time() - t0) * 1000)
            self.bids, self.asks, self.n = bids, asks, self.n + 1
            self.tape.extend(list(t) for t in trades)
            if bids and asks:
                (bp, bq, _), (ap, aq, _) = bids[0], asks[0]
                micro = (bp * aq + ap * bq) / (bq + aq) if bq + aq else (bp + ap) / 2
                self.hist.append((self.n, (bp + ap) / 2, micro))

    def loop(self) -> None:
        while True:
            if self.running:
                self.poll()
            time.sleep(INTERVAL)

    def state(self) -> dict:
        with self.lock:
            b, a, h = self.bids, self.asks, list(self.hist)
            mid = (b[0][0] + a[0][0]) / 2 if b and a else None
            spread = a[0][0] - b[0][0] if b and a else None
            micro = h[-1][2] if h else None
            dec = 4 if mid is None or mid < 100 else 2 if mid < 10000 else 1
            return {
                "live": True, "source": self.source, "symbol": self.symbol, "latency": self.latency,
                "err": self.err, "dec": dec, "backend": "live", "running": self.running, "speed": 1,
                "seed": 0, "strategy": "none", "step": self.n, "mid": mid, "spread": spread,
                "microprice": micro, "bids": b, "asks": a, "tape": list(self.tape), "cards": [],
                "hist": {"step": [x[0] for x in h], "mid": [x[1] for x in h], "fund": [x[2] for x in h], "pnl": {}},
            }

    def control(self, body: dict) -> dict:
        action = body["action"]
        if action not in ("play", "pause"):
            raise ValueError("only play/pause are available on a live feed")
        self.running = action == "play"
        return {"ok": True}

    def order(self, body: dict) -> dict:
        raise ValueError("live feed is read-only: no orders are sent anywhere")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m lob.live", description="Live read-only market data dashboard")
    p.add_argument("--source", choices=list(FEEDS), default="kraken")
    p.add_argument("--symbol", help="kraken: XBTUSD, ETHUSD ...   coinbase: BTC-USD, ETH-USD ...")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)
    sess = LiveSession(a.source, a.symbol)
    httpd = _bind(a.host, a.port, _handler(sess))
    threading.Thread(target=sess.loop, daemon=True).start()
    print(f"lob LIVE {sess.source} {sess.symbol} (read-only): http://{a.host}:{httpd.server_address[1]}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()