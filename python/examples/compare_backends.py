"""C++ vs pure-Python engine on the identical workload: same results, very different speed."""

import random
import time

import lob
from lob import Side

N = 200_000


def workload(book):
    rng = random.Random(123)
    live, t0 = [], time.perf_counter()
    for _ in range(N):
        r = rng.random()
        if r < 0.3 and live:
            book.cancel(live.pop(rng.randrange(len(live))))
        elif r < 0.35:
            book.market(Side.Buy if rng.random() < 0.5 else Side.Sell, rng.randint(1, 50))
        else:
            side = Side.Buy if rng.random() < 0.5 else Side.Sell
            px = 10_000 + rng.randint(-30, 30)
            res = book.limit(side, px, rng.randint(1, 50))
            if res.resting:
                live.append(res.order_id)
    return time.perf_counter() - t0


out = {}
for backend in ["python"] + (["cpp"] if lob.HAS_CPP else []):
    b = lob.OrderBook(backend=backend)
    b.set_record_tape(False)
    dt = workload(b)
    out[backend] = (dt, b.total_trades(), b.total_volume(), b.order_count(), b.best_bid(), b.best_ask())
    print(f"{backend:7s} {N/dt:12,.0f} ops/s   trades={out[backend][1]:,} volume={out[backend][2]:,} resting={out[backend][3]:,}")
if "cpp" in out:
    assert out["cpp"][1:] == out["python"][1:], "backends diverged!"
    print(f"identical final state; C++ is {out['python'][0]/out['cpp'][0]:.1f}x faster through the Python API")
    print("(the gap is much larger without Python call overhead - see lob_bench)")
else:
    print("C++ extension not built: pip install .")
