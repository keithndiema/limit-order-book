"""SQLite persistence + the bundled analytical SQL queries."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .simulator import SNAPSHOT_COLUMNS, SimResult

_SQL_DIR = Path(__file__).with_name("sql")


def available_queries() -> List[str]:
    return sorted(p.stem for p in (_SQL_DIR / "queries").glob("*.sql"))


def query_text(name: str) -> str:
    return (_SQL_DIR / "queries" / f"{name}.sql").read_text()


def write_sqlite(result: SimResult, path: str = "results/lob.sqlite") -> sqlite3.Connection:
    """Create (or overwrite) a SQLite database holding the run. Returns an open connection."""
    Path(path).parent.mkdir(parents=True, exist_ok=True) if path != ":memory:" else None
    con = sqlite3.connect(path)
    con.executescript((_SQL_DIR / "schema.sql").read_text())
    n = len(result.snapshots["step"])
    rows = [tuple(result.snapshots[c][i] for c in SNAPSHOT_COLUMNS) for i in range(n)]
    con.executemany(f"INSERT INTO snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES ({','.join('?' * len(SNAPSHOT_COLUMNS))})", rows)
    con.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?)", result.trades)
    con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", result.events)
    con.executemany("INSERT INTO strategy_pnl VALUES (?,?,?,?,?,?)", result.pnl)
    con.commit()
    return con


def run_query(con: sqlite3.Connection, name: str) -> Tuple[List[str], List[tuple]]:
    cur = con.execute(query_text(name))
    return [d[0] for d in cur.description], cur.fetchall()


def format_table(cols: Sequence[str], rows: Sequence[tuple], max_rows: int = 12) -> str:
    shown = [tuple("" if v is None else v for v in r) for r in rows[:max_rows]]
    widths = [max(len(str(c)), *(len(str(r[i])) for r in shown)) if shown else len(str(c)) for i, c in enumerate(cols)]
    line = "  ".join(str(c).rjust(w) for c, w in zip(cols, widths))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(str(v).rjust(w) for v, w in zip(r, widths)) for r in shown]
    if len(rows) > max_rows:
        out.append(f"... ({len(rows) - max_rows} more rows)")
    return "\n".join(out)
