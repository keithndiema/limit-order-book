#!/usr/bin/env Rscript
# Statistical microstructure analysis of a simulation run (base R only: no packages to install).
#
#   Rscript r/analyze.R [results_dir]
#
# Reads  <dir>/snapshots.csv, trades.csv, pnl.csv   (written by `lob simulate`)
# Writes <dir>/r_*.png and <dir>/r_summary.csv

args <- commandArgs(trailingOnly = TRUE)
dir  <- if (length(args) >= 1) args[1] else "results"
need <- file.path(dir, c("snapshots.csv", "trades.csv", "pnl.csv"))
if (!all(file.exists(need))) stop("missing input; run `lob simulate --out ", dir, "` first")

snap   <- read.csv(file.path(dir, "snapshots.csv"))
trades <- read.csv(file.path(dir, "trades.csv"))
pnl    <- read.csv(file.path(dir, "pnl.csv"), stringsAsFactors = FALSE)
source(file.path(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])), "metrics.R"))

cat("=== Limit order book: R analysis ===\n")
cat(sprintf("steps: %d | trades: %d | volume: %d\n\n", nrow(snap), nrow(trades), sum(trades$quantity)))

# ---- 1. quoted spread -------------------------------------------------------------------------
sp <- snap$spread[!is.na(snap$spread)]
cat("Spread (ticks): mean", round(mean(sp), 3), "| median", median(sp), "| p95", quantile(sp, 0.95), "\n")

# ---- 2. mid-price returns: autocorrelation (bid-ask bounce => negative lag-1) ------------------
ret <- diff(snap$mid); ret <- ret[!is.na(ret)]
ac  <- acf(ret, lag.max = 20, plot = FALSE)
cat("Mid-change ACF lag 1:", round(ac$acf[2], 4), "(95% band +/-", round(1.96 / sqrt(length(ret)), 4), ")\n")
ljung <- Box.test(ret, lag = 10, type = "Ljung-Box")
cat("Ljung-Box (10 lags) p-value:", signif(ljung$p.value, 3), "\n")

# ---- 3. order-flow imbalance -> price impact (Cont, Kukanov & Stoikov 2014) -------------------
ofi <- compute_ofi(snap)
dm  <- c(NA, diff(snap$mid))
ok  <- is.finite(ofi) & is.finite(dm)
fit <- lm(dm[ok] ~ ofi[ok])
sfit <- summary(fit)
cat(sprintf("Price impact: %.5f ticks per lot of OFI (t = %.1f, R^2 = %.3f)\n",
            coef(fit)[2], sfit$coefficients[2, 3], sfit$r.squared))

# ---- 4. strategy performance ------------------------------------------------------------------
strategies <- unique(pnl$strategy)
perf <- do.call(rbind, lapply(strategies, function(s) strategy_metrics(pnl[pnl$strategy == s, ], s)))
if (!is.null(perf)) { cat("\nStrategy performance (marked to mid):\n"); print(perf, row.names = FALSE) }

# ---- 5. adverse selection: markout of passive fills --------------------------------------------
h <- 10
mid_by_step <- setNames(snap$mid, snap$step)
trades$future_mid <- mid_by_step[as.character(trades$step + h)]
trades$passive_owner  <- ifelse(trades$aggressor == 0, trades$seller_owner, trades$buyer_owner)
trades$passive_profit <- ifelse(trades$aggressor == 0, trades$price - trades$future_mid,
                                trades$future_mid - trades$price)
tf <- trades[is.finite(trades$passive_profit), ]
mk <- data.frame(passive_owner = sort(unique(tf$passive_owner)))
mk$fills <- as.integer(table(tf$passive_owner)[mk$passive_owner])
mk$markout_ticks <- round(tapply(tf$passive_profit, tf$passive_owner, mean)[mk$passive_owner], 3)
cat(sprintf("\nPassive-side markout at +%d steps (ticks/lot):\n", h)); print(mk, row.names = FALSE)

# ---- plots ------------------------------------------------------------------------------------
png(file.path(dir, "r_spread_hist.png"), 900, 540, res = 130)
barplot(table(factor(pmin(sp, 15), levels = 1:15)) / length(sp) * 100, col = "#3b6fd4", border = "white",
        main = "Quoted spread distribution", xlab = "Spread (ticks, 15 = 15+)", ylab = "% of steps")
invisible(dev.off())

png(file.path(dir, "r_acf.png"), 900, 540, res = 130)
plot(ac, main = "Autocorrelation of mid-price changes", col = "#3b6fd4", lwd = 2)
invisible(dev.off())

png(file.path(dir, "r_ofi_impact.png"), 900, 560, res = 130)
idx <- which(ok); if (length(idx) > 6000) idx <- sample(idx, 6000)
plot(ofi[idx], dm[idx], pch = 16, cex = 0.4, col = adjustcolor("#3b6fd4", 0.35),
     xlab = "Order-flow imbalance (lots)", ylab = "Mid-price change (ticks)",
     main = sprintf("Price impact of order flow (slope %.4f, R2 %.2f)", coef(fit)[2], sfit$r.squared))
abline(fit, col = "#d6455d", lwd = 2)
invisible(dev.off())

if (length(strategies) > 0) {
  cols <- c("#3b6fd4", "#d6455d", "#2e9e6b", "#e08a1e")
  png(file.path(dir, "r_strategies.png"), 1000, 760, res = 130)
  par(mfrow = c(2, 1), mar = c(3.5, 4.5, 2, 1))
  plot(range(pnl$step), range(pnl$mtm_pnl), type = "n", xlab = "", ylab = "Mark-to-mid PnL", main = "Market-maker PnL")
  for (i in seq_along(strategies)) { d <- pnl[pnl$strategy == strategies[i], ]; lines(d$step, d$mtm_pnl, col = cols[i], lwd = 1.5) }
  legend("topleft", strategies, col = cols[seq_along(strategies)], lwd = 2, bty = "n")
  plot(range(pnl$step), range(pnl$inventory), type = "n", xlab = "Step", ylab = "Inventory (lots)", main = "Inventory")
  for (i in seq_along(strategies)) { d <- pnl[pnl$strategy == strategies[i], ]; lines(d$step, d$inventory, col = cols[i], lwd = 1) }
  abline(h = 0, lty = 3)
  invisible(dev.off())
}

summary_df <- data.frame(
  metric = c("steps", "trades", "volume", "mean_spread", "acf_lag1", "impact_ticks_per_lot", "impact_r2"),
  value  = c(nrow(snap), nrow(trades), sum(trades$quantity), mean(sp), ac$acf[2], coef(fit)[2], sfit$r.squared))
write.csv(summary_df, file.path(dir, "r_summary.csv"), row.names = FALSE)
cat("\nwrote r_spread_hist.png r_acf.png r_ofi_impact.png r_strategies.png r_summary.csv to", dir, "\n")
