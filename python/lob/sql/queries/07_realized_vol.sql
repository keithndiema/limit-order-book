-- Rolling 100-step realised volatility of mid changes, sampled every 1,000 steps.
WITH d AS (
    SELECT step, mid - LAG(mid) OVER (ORDER BY step) AS dm FROM snapshots
), r AS (
    SELECT step,
           SQRT(AVG(dm*dm) OVER w - AVG(dm) OVER w * AVG(dm) OVER w) AS vol100
    FROM d
    WINDOW w AS (ORDER BY step ROWS BETWEEN 99 PRECEDING AND CURRENT ROW)
)
SELECT step, ROUND(vol100, 4) AS realised_vol_ticks
FROM r
WHERE step % 1000 = 999 AND vol100 IS NOT NULL
ORDER BY step;
