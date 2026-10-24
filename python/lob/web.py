"""Live dashboard: `python -m lob serve` -> http://127.0.0.1:8000 (stdlib only, no extra dependencies)."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .simulator import MarketSimulator, SimConfig
from .strategies import AvellanedaStoikovMM, FixedSpreadMM
from .types import Side

HIST = 400
LEVELS = 15
STRATEGIES = ("fixed", "as", "both", "none")
INDEX = Path(__file__).parent / "static" / "index.html"


class Session:
    """One live simulation. All access goes through `lock`; memory stays bounded (results are drained each tick)."""

    def __init__(self, seed: int = 42, strategy: str = "both", backend: str = "auto"):
        self.lock = threading.RLock()
        self.backend, self.running, self.speed = backend, True, 5
        self.seed, self.strategy = int(seed), strategy
        self.reset()

    def reset(self, seed=None, strategy=None) -> None:
        with self.lock:
            if strategy is not None and strategy not in STRATEGIES:
                raise ValueError(f"strategy must be one of {STRATEGIES}")
            if seed is not None:
                self.seed = int(seed)
            if strategy is not None:
                self.strategy = strategy
            sim = MarketSimulator(SimConfig(seed=self.seed), backend=self.backend)
            if self.strategy in ("fixed", "both"):
                sim.add_strategy(FixedSpreadMM())
            if self.strategy in ("as", "both"):
                sim.add_strategy(AvellanedaStoikovMM())
            self.sim = sim
            self.hist, self.tape = deque(maxlen=HIST), deque(maxlen=40)
            self.you_inv = self.you_fills = 0
            self.you_cash = 0.0

    # ------------------------------------------------------------------ stepping
    def _cards(self) -> list:
        mid = self.sim.book.mid_price()
        ref = mid if mid is not None else self.sim.fundamental
        cards = [{"name": s.name, "inv": s.inventory, "pnl": round(s.cash + s.inventory * ref, 1),
                  "fills": s.fill_count} for s in self.sim.strategies]
        cards.append({"name": "you", "inv": self.you_inv, "pnl": round(self.you_cash + self.you_inv * ref, 1),
                      "fills": self.you_fills})
        return cards

    def _advance(self, n: int) -> None:
        sim, res = self.sim, self.sim.result
        n0 = len(res.trades)
        sim.run(n)
        for tr in res.trades[n0:]:  # (id, step, buy_id, sell_id, price, qty, aggressor, buyer, seller)
            self.tape.append([tr[1], tr[4], tr[5], tr[6]])
            for owner, sgn in ((tr[7], 1), (tr[8], -1)):
                if owner == "you":
                    self.you_inv += sgn * tr[5]
                    self.you_cash -= sgn * tr[4] * tr[5]
                    self.you_fills += 1
        res.trades.clear(); res.events.clear(); res.pnl.clear()  # keep memory flat on long runs
        for col in res.snapshots.values():
            col.clear()
        self.hist.append((sim.step, sim.book.mid_price(), round(sim.fundamental, 2),
                          [c["pnl"] for c in self._cards()]))

    def loop(self) -> None:
        while True:
            time.sleep(0.1)
            with self.lock:
                if self.running:
                    self._advance(self.speed)

    # ------------------------------------------------------------------ API
    def state(self) -> dict:
        with self.lock:
            if not self.hist:
                self._advance(1)  # first paint needs a warmed-up book
            b = self.sim.book
            cards = self._cards()
            lv = lambda ls: [[l.price, l.quantity, l.order_count] for l in ls]
            h = list(self.hist)
            return {
                "backend": self.sim.backend, "running": self.running, "speed": self.speed,
                "seed": self.seed, "strategy": self.strategy, "step": self.sim.step,
                "mid": b.mid_price(), "spread": b.spread(), "microprice": b.microprice(),
                "bids": lv(b.bid_levels(LEVELS)), "asks": lv(b.ask_levels(LEVELS)),
                "tape": list(self.tape), "cards": cards,
                "hist": {"step": [x[0] for x in h], "mid": [x[1] for x in h], "fund": [x[2] for x in h],
                         "pnl": {c["name"]: [x[3][i] for x in h] for i, c in enumerate(cards)}},
            }

    def control(self, body: dict) -> dict:
        action = body["action"]
        with self.lock:
            if action == "play":
                self.running = True
            elif action == "pause":
                self.running = False
            elif action == "speed":
                self.speed = max(1, min(500, int(body["speed"])))
            elif action == "reset":
                self.reset(body.get("seed"), body.get("strategy"))
            else:
                raise ValueError(f"unknown action {action!r}")
        return {"ok": True}

    def order(self, body: dict) -> dict:
        if body["side"] not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        side, qty = (Side.Buy if body["side"] == "buy" else Side.Sell), int(body["qty"])
        with self.lock:
            if body.get("type", "limit") == "market":
                res = self.sim.place_market("you", side, qty)
            else:
                res = self.sim.place("you", side, int(body["price"]), qty)
            if not self.running:
                self._advance(1)  # paused: tick once so the fill is reconciled
            return {"accepted": res.accepted, "filled": res.filled, "remaining": res.remaining,
                    "reject": getattr(res.reject, "name", str(res.reject))}


def _handler(sess: Session):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send(200, sess.state())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            routes = {"/api/control": sess.control, "/api/order": sess.order}
            fn = routes.get(self.path)
            if fn is None:
                return self._send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                self._send(200, fn(json.loads(self.rfile.read(n) or b"{}")))
            except (ValueError, KeyError, TypeError) as e:
                self._send(400, {"error": f"bad request: {e}"})

        def log_message(self, *args):  # keep the terminal quiet
            pass

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, seed: int = 42, strategy: str = "both",
          backend: str = "auto") -> None:
    sess = Session(seed, strategy, backend)
    threading.Thread(target=sess.loop, daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), _handler(sess))
    print(f"lob dashboard ({sess.sim.backend} backend): http://{host}:{port}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
