# Microstructure notes

Short, practical background for the quantities this project computes.

## The book and price-time priority
Buyers' resting limit orders form the **bid** side, sellers' the **ask** side. An arriving order that crosses the spread
trades immediately (it is the *aggressor*, or taker); one that does not rests (it *provides* liquidity). Orders at the
best price are served first-in-first-out, so queue position has value, which is why `reduce` keeps priority and `replace` forfeits it.

## Spread, mid and microprice
* `spread = best_ask - best_bid`, the price of immediacy.
* `mid = (bid + ask) / 2`.
* `microprice = (bid * ask_qty + ask * bid_qty) / (bid_qty + ask_qty)`. It leans toward the *thinner* side, because
  a thin ask is about to be eaten and the price is more likely to tick up. It is a better short-horizon fair-value estimate than the mid.

## Order-flow imbalance (OFI) and price impact
Cont, Kukanov & Stoikov (2014) show that short-horizon mid-price changes are mostly explained by the net change in
best-level queue sizes:

```
e_n = 1{Pb_n >= Pb_{n-1}} qb_n - 1{Pb_n <= Pb_{n-1}} qb_{n-1} - 1{Pa_n <= Pa_{n-1}} qa_n + 1{Pa_n >= Pa_{n-1}} qa_{n-1}
d(mid) = a + lambda * OFI + noise
```
`lambda` (ticks per lot) is the *price impact*; it is reported by Python (`lob.analytics`), SQL (`04_ofi_price_impact.sql`) and R (`r/analyze.R`), and the three agree.

## Adverse selection and markouts
A passive fill is not free money: the people who hit your quote may know something. The **markout** of a passive fill is
the profit you would have made closing out at the mid `h` steps later (`05_markouts.sql`). If the average markout is below the half-spread
you quoted, the difference is what informed flow took from you. In the simulator, a fraction of market orders trades in the
direction of `fundamental - mid`, which creates exactly this effect.

## Avellaneda-Stoikov market making
For a risk-averse maker with inventory `q` facing mid-price volatility `sigma` and order-arrival intensity decaying with distance
as `exp(-k * delta)`:

```
reservation price  r     = s - q * gamma * sigma^2 * (T - t)
optimal total spread delta = gamma * sigma^2 * (T - t) + (2 / gamma) * ln(1 + gamma / k)
```
Long inventory pushes the reservation price *down* so you sell more readily; short pushes it up. The strategy here uses the
stationary form (fixed effective horizon `H`) and an EWMA volatility estimate.

**Caveat worth knowing:** the formula assumes uninformed flow, so on its own it quotes *too tight* in a market with informed traders
(try `min_half_spread=1`; it loses money). The `min_half_spread` floor is effectively an adverse-selection charge, and that is
the interesting empirical finding in `python/examples/compare_strategies.py`.

## References
* Avellaneda & Stoikov (2008), *High-frequency trading in a limit order book*, Quantitative Finance.
* Cont, Kukanov & Stoikov (2014), *The price impact of order book events*, Journal of Financial Econometrics.
* Glosten & Milgrom (1985), *Bid, ask and transaction prices in a specialist market with heterogeneously informed traders*.
* Gould et al. (2013), *Limit order books*, Quantitative Finance.
