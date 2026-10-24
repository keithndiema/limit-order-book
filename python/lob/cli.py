"""`lob` command line: demo / simulate / sql / serve."""

from __future__ import annotations

import argparse
import sys

from . import HAS_CPP, __version__
from .book import OrderBook
from .simulator import MarketSimulator, SimConfig
from .strategies import AvellanedaStoikovMM, FixedSpreadMM


def ladder(book, depth: int = 6) -> str:
    asks, bids = book.ask_levels(depth), book.bid_levels(depth)
    scale = max([l.quantity for l in asks + bids] + [1])
    bar = lambda q: "#" * max(1, round(24 * q / scale))
    lines = ["        price    qty"]
    for l in reversed(asks):
        lines.append(f"  ASK {l.price:>8} {l.quantity:>6}  {bar(l.quantity)}")
    s, m = book.spread(), book.mid_price()
    lines.append(f"  --- spread {s} | mid {m:.1f} ---" if s is not None else "  --- one-sided ---")
    for l in bids:
        lines.append(f"  BID {l.price:>8} {l.quantity:>6}  {bar(l.quantity)}")
    return "\n".join(lines)


def _simulate(args) -> int:
    sim = MarketSimulator(SimConfig(n_steps=args.steps, seed=args.seed), backend=args.backend)
    if args.strategy in ("fixed", "both"):
        sim.add_strategy(FixedSpreadMM())
    if args.strategy in ("as", "both"):
        sim.add_strategy(AvellanedaStoikovMM())
    result = sim.run()
    print(f"backend={sim.backend}  steps={args.steps:,}  trades={len(result.trades):,}  "
          f"events={len(result.events):,}  final BBO={sim.book.best_bid()}/{sim.book.best_ask()}")
    print(ladder(sim.book))
    from .analytics import impact_from_result, strategy_report
    for s in result.strategies:
        rep = strategy_report([r for r in result.pnl if r[0] == s.name])
        print(f"  {s.name:20s} pnl={rep['final_pnl']:9.0f}  inv_sd={rep['inventory_sd']:6.1f}  "
              f"max|inv|={rep['max_abs_inventory']:5.0f}  fills={s.fill_count}")
    imp = impact_from_result(result)
    print(f"  price impact: {imp['slope']:.4f} ticks per lot of OFI (R^2={imp['r2']:.2f})")
    if args.out:
        paths = result.export_csv(args.out)
        print("wrote", ", ".join(str(p) for p in paths.values()))
        if args.sqlite:
            from .store import write_sqlite
            write_sqlite(result, f"{args.out}/lob.sqlite").close()
            print(f"wrote {args.out}/lob.sqlite")
        if args.plots:
            from .viz import plot_depth, plot_run
            plot_run(result, f"{args.out}/simulation.png")
            plot_depth(sim.book, path=f"{args.out}/depth.png")
    return 0


def _sql(args) -> int:
    import sqlite3
    from .store import available_queries, format_table, run_query
    con = sqlite3.connect(args.db)
    names = [args.query] if args.query else available_queries()
    for n in names:
        cols, rows = run_query(con, n)
        print(f"\n-- {n}\n{format_table(cols, rows)}")
    return 0


def _serve(args) -> int:
    from .web import serve
    serve(args.host, args.port, args.seed, args.strategy, args.backend)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lob", description="Limit order book toolkit")
    p.add_argument("--version", action="version", version=f"lob {__version__} (C++ backend: {HAS_CPP})")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="30-second tour: simulate a market with two market makers")
    d.set_defaults(func=lambda a: _simulate(argparse.Namespace(steps=5000, seed=7, strategy="both", backend="auto",
                                                               out=None, sqlite=False, plots=False)))
    s = sub.add_parser("simulate", help="run a simulation and export CSV / SQLite / plots")
    s.add_argument("--steps", type=int, default=20000)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--strategy", choices=["fixed", "as", "both", "none"], default="both")
    s.add_argument("--backend", choices=["auto", "cpp", "python"], default="auto")
    s.add_argument("--out", default="results")
    s.add_argument("--sqlite", action="store_true", help="also write results/lob.sqlite")
    s.add_argument("--plots", action="store_true", help="also write PNG plots")
    s.set_defaults(func=_simulate)
    q = sub.add_parser("sql", help="run the bundled analytical SQL queries against a lob.sqlite file")
    q.add_argument("db")
    q.add_argument("--query", help="e.g. 05_markouts (default: all)")
    q.set_defaults(func=_sql)
    v = sub.add_parser("serve", help="live browser dashboard (order book, depth, PnL, manual orders)")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--seed", type=int, default=42)
    v.add_argument("--strategy", choices=["fixed", "as", "both", "none"], default="both")
    v.add_argument("--backend", choices=["auto", "cpp", "python"], default="auto")
    v.set_defaults(func=_serve)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
