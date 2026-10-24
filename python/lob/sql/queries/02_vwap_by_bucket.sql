-- OHLC + VWAP per 1,000-step bucket.
WITH t AS (
    SELECT step / 1000 AS bucket, step, price, quantity,
           ROW_NUMBER() OVER (PARTITION BY step / 1000 ORDER BY trade_id)      AS rn_first,
           ROW_NUMBER() OVER (PARTITION BY step / 1000 ORDER BY trade_id DESC) AS rn_last
    FROM trades
)
SELECT bucket,
       MAX(CASE WHEN rn_first = 1 THEN price END)         AS open,
       MAX(price)                                         AS high,
       MIN(price)                                         AS low,
       MAX(CASE WHEN rn_last  = 1 THEN price END)         AS close,
       ROUND(1.0 * SUM(price * quantity) / SUM(quantity), 2) AS vwap,
       SUM(quantity)                                      AS volume,
       COUNT(*)                                           AS trades
FROM t
GROUP BY bucket
ORDER BY bucket;
