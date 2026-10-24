# Reusable metric helpers (sourced by analyze.R; also usable interactively).

# Best-level order-flow imbalance, Cont-Kukanov-Stoikov (2014). Positive = net buying pressure.
compute_ofi <- function(snap) {
  ffill <- function(x) { for (i in seq_along(x)[-1]) if (is.na(x[i])) x[i] <- x[i - 1]; x }
  bp <- ffill(snap$best_bid); bq <- ffill(snap$bid_qty)
  ap <- ffill(snap$best_ask); aq <- ffill(snap$ask_qty)
  n <- length(bp); e <- rep(NA_real_, n); e[1] <- 0
  i <- 2:n; j <- i - 1
  e[i] <- (bp[i] >= bp[j]) * bq[i] - (bp[i] <= bp[j]) * bq[j] -
          (ap[i] <= ap[j]) * aq[i] + (ap[i] >= ap[j]) * aq[j]
  e
}

max_drawdown <- function(equity) max(cummax(equity) - equity)

strategy_metrics <- function(d, name) {
  d <- d[order(d$step), ]
  step_pnl <- diff(d$mtm_pnl)
  data.frame(
    strategy      = name,
    final_pnl     = round(tail(d$mtm_pnl, 1), 0),
    max_drawdown  = round(max_drawdown(d$mtm_pnl), 0),
    inventory_sd  = round(sd(d$inventory), 1),
    max_abs_inv   = max(abs(d$inventory)),
    step_sharpe   = round(mean(step_pnl) / sd(step_pnl), 4)
  )
}
