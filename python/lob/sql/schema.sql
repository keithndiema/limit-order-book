-- Relational model of one simulation run. Portable SQL (tested on SQLite >= 3.25 for window
-- functions; the queries also run on PostgreSQL/DuckDB with trivial changes).

DROP TABLE IF EXISTS snapshots;
DROP TABLE IF EXISTS trades;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS strategy_pnl;

-- One row per simulation step: top of book, depth, flow.
CREATE TABLE snapshots (
    step            INTEGER PRIMARY KEY,
    fundamental     REAL,
    best_bid        INTEGER,
    bid_qty         INTEGER,
    best_ask        INTEGER,
    ask_qty         INTEGER,
    mid             REAL,
    microprice      REAL,
    spread          INTEGER,
    bid_depth5      INTEGER,
    ask_depth5      INTEGER,
    trades          INTEGER NOT NULL,
    volume          INTEGER NOT NULL,
    signed_volume   INTEGER NOT NULL,   -- + = buyer-initiated
    resting_orders  INTEGER NOT NULL
);

-- One row per execution. aggressor: 0 = buyer-initiated, 1 = seller-initiated.
CREATE TABLE trades (
    trade_id        INTEGER PRIMARY KEY,
    step            INTEGER NOT NULL REFERENCES snapshots(step),
    buy_order_id    INTEGER NOT NULL,
    sell_order_id   INTEGER NOT NULL,
    price           INTEGER NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    aggressor       INTEGER NOT NULL CHECK (aggressor IN (0, 1)),
    buyer_owner     TEXT NOT NULL,
    seller_owner    TEXT NOT NULL
);

-- Order-entry log (what every participant sent).
CREATE TABLE events (
    event_id        INTEGER PRIMARY KEY,
    step            INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('LIMIT', 'MARKET', 'CANCEL')),
    owner           TEXT NOT NULL,
    order_id        INTEGER NOT NULL,
    side            INTEGER,
    price           INTEGER,
    quantity        INTEGER
);

-- Marked-to-mid strategy accounting, one row per strategy per step.
CREATE TABLE strategy_pnl (
    strategy        TEXT NOT NULL,
    step            INTEGER NOT NULL,
    inventory       INTEGER NOT NULL,
    cash            REAL NOT NULL,
    mid             REAL NOT NULL,
    mtm_pnl         REAL NOT NULL,
    PRIMARY KEY (strategy, step)
);

CREATE INDEX idx_trades_step   ON trades(step);
CREATE INDEX idx_events_owner  ON events(owner, kind);
