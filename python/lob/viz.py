"""matplotlib helpers (optional dependency)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:  # pragma: no cover
    HAS_MPL = False

BID, ASK, ACC = "#2e9e6b", "#d6455d", "#3b6fd4"


def _need_mpl() -> bool:
    if not HAS_MPL:
        print("matplotlib not installed - skipping plot (pip install matplotlib)")
    return HAS_MPL


def _style(ax):
    ax.grid(True, alpha=0.25)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def plot_depth(book, levels: int = 15, path: str = "results/depth.png", title: str = "Order book depth") -> Optional[str]:
    """Cumulative depth chart (the classic 'mountain' view)."""
    if not _need_mpl():
        return None
    bids, asks = book.bid_levels(levels), book.ask_levels(levels)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    if bids:
        px = [l.price for l in bids]
        ax.fill_between(px, np.cumsum([l.quantity for l in bids]), step="post", color=BID, alpha=0.35)
        ax.step(px, np.cumsum([l.quantity for l in bids]), where="post", color=BID, label="Bids")
    if asks:
        px = [l.price for l in asks]
        ax.fill_between(px, np.cumsum([l.quantity for l in asks]), step="pre", color=ASK, alpha=0.35)
        ax.step(px, np.cumsum([l.quantity for l in asks]), where="pre", color=ASK, label="Asks")
    ax.set_xlabel("Price (ticks)")
    ax.set_ylabel("Cumulative quantity (lots)")
    ax.set_title(title)
    ax.legend(frameon=False)
    _style(ax)
    return _save(fig, path)


def plot_run(result, path: str = "results/simulation.png") -> Optional[str]:
    """Four-panel dashboard: price vs fundamental, spread, inventory, PnL."""
    if not _need_mpl():
        return None
    c = result.column
    step = c("step")
    fig, axes = plt.subplots(4, 1, figsize=(10, 9), sharex=True)
    axes[0].plot(step, c("fundamental"), color="#888", lw=0.9, label="fundamental")
    axes[0].plot(step, c("mid"), color=ACC, lw=0.9, label="book mid")
    axes[0].set_ylabel("Price (ticks)")
    axes[0].legend(frameon=False, ncol=2)
    axes[0].set_title(f"Simulation run ({result.backend} backend, {len(step):,} steps)")
    axes[1].plot(step, c("spread"), color="#e08a1e", lw=0.7)
    axes[1].set_ylabel("Spread")
    for s in result.strategies:
        rows = [r for r in result.pnl if r[0] == s.name]
        st = [r[1] for r in rows]
        axes[2].plot(st, [r[2] for r in rows], lw=0.8, label=s.name)
        axes[3].plot(st, [r[5] for r in rows], lw=1.0, label=s.name)
    axes[2].set_ylabel("Inventory (lots)")
    axes[3].set_ylabel("Mark-to-mid PnL")
    axes[3].set_xlabel("Step")
    if result.strategies:
        axes[2].legend(frameon=False)
    for a in axes:
        _style(a)
    return _save(fig, path)


def plot_benchmark(json_path: str, path: str = "docs/assets/benchmark.png") -> Optional[str]:
    """Bar chart of throughput from `lob_bench --json` output."""
    if not _need_mpl():
        return None
    import json
    data = json.load(open(json_path))["results"]
    loads = sorted({r["workload"] for r in data}, key=lambda w: [r["workload"] for r in data].index(w))
    fig, ax = plt.subplots(figsize=(8, 4.2))
    width = 0.38
    for i, impl, col in ((0, "ReferenceBook", "#aab4c8"), (1, "OrderBook", ACC)):
        vals = [next(r["mops"] for r in data if r["workload"] == w and r["impl"] == impl) for w in loads]
        bars = ax.bar(np.arange(len(loads)) + (i - 0.5) * width, vals, width, color=col, label=impl)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(np.arange(len(loads)))
    ax.set_xticklabels(loads)
    ax.set_ylabel("Million operations / second")
    ax.set_title("Throughput: optimised book vs std::map baseline (single thread)")
    ax.legend(frameon=False)
    _style(ax)
    return _save(fig, path)


def _save(fig, path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path
