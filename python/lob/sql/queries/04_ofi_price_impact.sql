-- Order-flow imbalance (Cont-Kukanov-Stoikov) per step via LAG, then the price-impact regression
--   d(mid) = a + lambda * OFI
-- computed in pure SQL from aggregates:  lambda = (n*Sxy - Sx*Sy) / (n*Sxx - Sx^2),  R^2 = corr^2.
WITH lagged AS (
    SELECT step, mid, best_bid, bid_qty, best_ask, ask_qty,
           LAG(mid)      OVER w AS mid0,
           LAG(best_bid) OVER w AS bp0, LAG(bid_qty) OVER w AS bq0,
           LAG(best_ask) OVER w AS ap0, LAG(ask_qty) OVER w AS aq0
    FROM snapshots
    WINDOW w AS (ORDER BY step)
), ofi AS (
    SELECT step,
           (CASE WHEN best_bid >= bp0 THEN bid_qty ELSE 0 END)
         - (CASE WHEN best_bid <= bp0 THEN bq0     ELSE 0 END)
         - (CASE WHEN best_ask <= ap0 THEN ask_qty ELSE 0 END)
         + (CASE WHEN best_ask >= ap0 THEN aq0     ELSE 0 END)  AS x,
           mid - mid0                                            AS y
    FROM lagged
    WHERE mid0 IS NOT NULL AND bp0 IS NOT NULL AND ap0 IS NOT NULL AND mid IS NOT NULL
), s AS (
    SELECT COUNT(*) AS n, SUM(x) AS sx, SUM(y) AS sy, SUM(x*y) AS sxy, SUM(x*x) AS sxx, SUM(y*y) AS syy
    FROM ofi
)
SELECT n                                                                 AS observations,
       ROUND((n*sxy - sx*sy) / (n*sxx - sx*sx), 6)                       AS impact_ticks_per_lot,
       ROUND(((n*sxy - sx*sy)*(n*sxy - sx*sy))
             / ((n*sxx - sx*sx) * (n*syy - sy*sy)), 4)                   AS r_squared
FROM s;
