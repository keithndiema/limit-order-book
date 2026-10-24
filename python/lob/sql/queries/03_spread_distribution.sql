-- Distribution of the quoted spread with cumulative share (window functions).
SELECT spread,
       COUNT(*)                                                     AS steps,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)           AS pct,
       ROUND(100.0 * SUM(COUNT(*)) OVER (ORDER BY spread)
                   / SUM(COUNT(*)) OVER (), 2)                      AS cum_pct
FROM snapshots
WHERE spread IS NOT NULL
GROUP BY spread
ORDER BY spread;
