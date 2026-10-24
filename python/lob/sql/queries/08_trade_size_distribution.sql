-- Trade-size buckets with share of count and share of volume.
SELECT CASE WHEN quantity <= 5  THEN '01-05'
            WHEN quantity <= 10 THEN '06-10'
            WHEN quantity <= 20 THEN '11-20'
            WHEN quantity <= 40 THEN '21-40'
            ELSE '41+' END                                           AS size_bucket,
       COUNT(*)                                                      AS trades,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)            AS pct_of_trades,
       ROUND(100.0 * SUM(quantity) / SUM(SUM(quantity)) OVER (), 2)  AS pct_of_volume
FROM trades
GROUP BY size_bucket
ORDER BY size_bucket;
