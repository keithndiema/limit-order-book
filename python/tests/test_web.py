import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from lob.web import Session, _handler


def make(**kw):
    s = Session(seed=3, strategy="both", backend="python", **kw)
    s.running = False
    return s


def test_state_shape_and_bounded_memory():
    s = make()
    s._advance(200)
    st = s.state()
    assert st["step"] == 200 and st["bids"] and st["asks"]
    assert [c["name"] for c in st["cards"]][-1] == "you"
    assert set(st["hist"]["pnl"]) == {c["name"] for c in st["cards"]}
    r = s.sim.result
    assert not r.trades and not r.events and not r.pnl and not r.snapshots["step"]


def test_manual_market_order_is_accounted():
    s = make()
    s.state()
    res = s.order({"side": "buy", "type": "market", "qty": 3})
    assert res["accepted"] and res["filled"] == 3
    you = s.state()["cards"][-1]
    assert you["inv"] == 3 and you["fills"] >= 1


def test_reset_and_validation():
    s = make()
    s._advance(50)
    s.control({"action": "reset", "seed": 9, "strategy": "none"})
    assert s.sim.step == 0 and s.seed == 9 and not s.sim.strategies
    with pytest.raises(ValueError):
        s.control({"action": "nope"})
    with pytest.raises(ValueError):
        s.control({"action": "reset", "strategy": "bogus"})
    with pytest.raises(ValueError):
        s.order({"side": "up", "qty": 1})


def test_http_roundtrip():
    s = make()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(s))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert b"lob live" in urllib.request.urlopen(base + "/").read()
        assert "mid" in json.load(urllib.request.urlopen(base + "/api/state"))
        req = urllib.request.Request(base + "/api/control", json.dumps({"action": "speed", "speed": 20}).encode())
        assert json.load(urllib.request.urlopen(req))["ok"] and s.speed == 20
        bad = urllib.request.Request(base + "/api/order", b"{}")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
