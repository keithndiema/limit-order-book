-- Headline statistics for the run.
SELECT
    COUNT(*)                                            AS steps,
    ROUND(AVG(spread), 3)                               AS avg_spread_ticks,
    MIN(spread)                                         AS min_spread,
    MAX(spread)                                         AS max_spread,
    SUM(trades)                                         AS trades,
    SUM(volume)                                         AS volume,
    ROUND(1.0 * SUM(CASE WHEN signed_volume > 0 THEN volume ELSE 0 END)
          / NULLIF(SUM(volume), 0), 3)                  AS buy_initiated_volume_share,
    ROUND(AVG(bid_depth5 + ask_depth5), 1)              AS avg_depth_top5_lots,
    ROUND(AVG(ABS(mid - fundamental)), 3)               AS avg_abs_mid_minus_fundamental
FROM snapshots;
