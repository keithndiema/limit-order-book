-- Markout of every fill from the *passive* (liquidity-providing) side's view, at +10 and +50 steps:
--   passive BOUGHT:  mid_{t+h} - price        passive SOLD:  price - mid_{t+h}
-- i.e. the passive party's profit per lot if it closed out at the later mid. Compare with the
-- half-spread it quoted: the gap is the cost of adverse selection.
SELECT owner, horizon, COUNT(*) AS fills, ROUND(AVG(markout), 4) AS avg_markout_ticks
FROM (
    SELECT CASE WHEN t.aggressor = 0 THEN t.seller_owner ELSE t.buyer_owner END AS owner,
           h.horizon,
           (CASE WHEN t.aggressor = 0 THEN -1 ELSE 1 END) * (s.mid - t.price)    AS markout
    FROM trades t
    CROSS JOIN (SELECT 10 AS horizon UNION ALL SELECT 50) h
    JOIN snapshots s ON s.step = t.step + h.horizon
    WHERE s.mid IS NOT NULL
)
GROUP BY owner, horizon
ORDER BY horizon, avg_markout_ticks;
