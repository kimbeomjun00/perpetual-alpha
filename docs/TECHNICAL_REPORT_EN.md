# Technical Report: Score-Aware Pair-Reversion Agent for PAS Testnet

## 1. Objective

The agent seeks positive, low-volatility daily account returns in the Perpetual Alpha scored phase. The design emphasizes market-neutral relative-value trades rather than directional forecasts. The implementation is restricted to PAS DEX on Hyperliquid Testnet.

## 2. Markets and portfolio

The portfolio contains two BTC-relative pairs: BTC–EWY and BTC–ETH. The current allocation is 85% BTC–EWY and 15% BTC–ETH. Gross exposure is 65% of account equity. Each pair is opened with equal-dollar BTC and non-BTC legs; the required long/short sides are derived from the observed residual.

## 3. Signal construction

For asset B and BTC, define hourly log returns \(r^B_t\) and \(r^{BTC}_t\). The rolling hedge coefficient is

\[
\beta_t = \frac{\operatorname{Cov}_W(r^{BTC}, r^B)}{\operatorname{Var}_W(r^{BTC})}.
\]

For lag \(L\), the relative residual is

\[
g_t = \log(P^B_t/P^B_{t-L}) - \beta_t\log(P^{BTC}_t/P^{BTC}_{t-L}).
\]

An entry is eligible only when rolling return correlation is at least 0.70 and \(|g_t|\ge 1.5\%\). A positive residual indicates that B has outperformed the beta-adjusted BTC move; the agent takes the opposite residual direction. Parameters are 24 hours / 12 hours for BTC–EWY and 72 hours / 3 hours for BTC–ETH.

## 4. Exit and risk rules

BTC–EWY exits at full residual recovery, 100% adverse widening, or 12 hours. BTC–ETH exits at 50% recovery, 50% adverse widening, or 24 hours. New entries are reduced by 25% when 24-hour BTC realized volatility is at least 0.6%. The execution engine also applies a -3% daily loss gate and a -6% high-water-mark drawdown gate. It refuses unknown positions, checks IOC fill deltas, and flattens tracked inventory on a material leg mismatch.

## 5. Competition-score alignment

The competition defines financial quality as

\[
Q=\frac{\max(R,0)+0.005}{|R|+1.5\sigma+0.05},
\]

where \(R\) is time-weighted return measured at daily 12:00 UTC account snapshots and \(\sigma\) is the annualized-to-period daily-return volatility specified by the competition. Before jury voting, leaderboard Score is \(0.8Q\). Therefore the strategy prioritizes positive daily snapshots and limits account-level volatility, rather than maximizing intraday turnover.

## 6. Historical validation

The score-aware validation uses aligned hourly historical BTC, ETH, and EWY data from 2026-03-19 through 2026-10-05. It replays the previously selected pair-return stream and samples equity at 12:00 UTC. The period is split chronologically into training, validation, and final test segments. No configuration was selected using validation or test results.

| Configuration | Train Score | Validation Score | Test Score |
|---|---:|---:|---:|
| 80% EWY / 20% ETH, 50% gross | 0.1584 | 0.0902 | 0.1048 |
| 85% EWY / 15% ETH, 50% gross | 0.1620 | 0.0994 | 0.1058 |
| 85% EWY / 15% ETH, 65% gross | 0.1734 | 0.1033 | 0.1125 |

The selected 85/15, 65% gross setting improved the pre-jury score in all three chronological segments within this deliberately small comparison set. This is evidence, not a performance guarantee.

## 7. Implementation and operations

`pas_pairs_shadow.py` reads public PAS candles and cannot sign or submit orders. `pas_pairs_live.py` requires both `--live-testnet` and `--arm` before it can use the Testnet order path. Credentials are read from a local `.env` file. The intended operational pattern is a short scheduled `--once` invocation: it evaluates completed data, records state and an audit log, then exits. This avoids reliance on an open terminal or a chat application.

## 8. Limitations

The validation is a historical proxy. It does not guarantee future correlation stability, fill quality, fee levels, slippage, or PAS Testnet liquidity. The comparison set is intentionally narrow to reduce parameter mining. Any live change should be monitored against daily 12:00 UTC score behavior and reverted if risk controls or execution quality deteriorate.
