-- Decompose each strategy's final PnL into spread capture and inventory (market) PnL.
--   spread capture  = sum over fills of side_sign * (mid_at_fill - price)   (edge vs mid at fill time)
--   inventory PnL   = total mark-to-mid PnL - spread capture                (what holding risk did)
WITH fills AS (
    SELECT t.buyer_owner AS strategy, 1 AS sgn, t.price, t.quantity, s.mid FROM trades t
      JOIN snapshots s ON s.step = t.step
    UNION ALL
    SELECT t.seller_owner, -1, t.price, t.quantity, s.mid FROM trades t
      JOIN snapshots s ON s.step = t.step
), edge AS (
    SELECT strategy,
           COUNT(*)                                   AS fills,
           SUM(quantity)                              AS volume,
           SUM(sgn * (mid - price) * quantity)        AS spread_capture
    FROM fills
    WHERE strategy IN (SELECT DISTINCT strategy FROM strategy_pnl) AND mid IS NOT NULL
    GROUP BY strategy
), last AS (
    SELECT p.strategy, p.mtm_pnl, p.inventory
    FROM strategy_pnl p
    JOIN (SELECT strategy, MAX(step) AS ms FROM strategy_pnl GROUP BY strategy) m
      ON m.strategy = p.strategy AND m.ms = p.step
)
SELECT l.strategy, e.fills, e.volume,
       ROUND(l.mtm_pnl, 1)                         AS total_pnl,
       ROUND(e.spread_capture, 1)                  AS spread_capture,
       ROUND(l.mtm_pnl - e.spread_capture, 1)      AS inventory_pnl,
       l.inventory                                 AS final_inventory
FROM last l LEFT JOIN edge e ON e.strategy = l.strategy
ORDER BY l.mtm_pnl DESC;
