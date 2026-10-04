# Counterparty Credit Risk & Exposure Analytics

A risk-management application built around the daily workflow of a Credit Risk /
Credit Risk Exposure Management team at an investment bank: it measures counterparty
exposure on an OTC derivative book, projects it under historical market scenarios,
applies collateral and margin, monitors credit limits and produces the daily risk pack.

```
Market Data -> Portfolio / Trades -> Historical Scenarios -> Exposure -> EE / PFE
            -> Collateral -> Initial Margin -> Limit Monitoring -> Breach Detection
            -> Counterparty Credit Analysis -> Risk Reporting
```

| Layer | Technology |
|---|---|
| Calculations | Python, NumPy, pandas, SciPy |
| Storage and querying | SQLite (`sql/schema.sql`, `sql/queries.sql`) |
| Dashboard | Streamlit + Plotly |
| Reporting | Excel via openpyxl, plus a VBA refresh macro |

---

## 1. Concepts and methodology

Every formula below is implemented as a small, separately tested function; the module
is given in brackets.

### Counterparty credit risk

Counterparty credit risk is the risk that the other side of a derivative defaults while
the trade has positive value to the bank. Unlike a loan, the amount at risk is not fixed:
it moves with the market, so it has to be measured as a distribution of possible future
values rather than as one number.

### Exposure (`ccr/exposure.py`)

For each trade and each historical scenario:

```
PnL change   = Sensitivity x Market Shock x Notional
Scenario MTM = Current MTM + PnL change
Exposure     = max(Scenario MTM, 0)
```

* **Market shock** - an observed move in the trade's risk factor over the scenario
  horizon (10 business days by default). Relative return for NIFTY 50 and USD/INR;
  absolute yield change for the interest-rate factor.
* **Sensitivity** - option delta (equity options), +1 / -1 (FX forwards bought / sold),
  signed duration (interest-rate swaps: positive when paying fixed).
* **Notional** - converted to INR at the valuation-date USD/INR spot.

Counterparty measures:

| Measure | Definition |
|---|---|
| Current exposure | `max(sum of trade MTMs, 0)` |
| Gross exposure | `sum of max(trade MTM, 0)` |
| Net exposure | `max(Gross Exposure - Collateral, 0)` |
| Exposure distribution | counterparty exposure in each of the 500 scenarios |

The scenario distribution is aggregated `gross` by default (sum of positive trade
exposures, no netting benefit). Setting `aggregation = "netted"` in the config treats
each counterparty as a single close-out netting set.

### Expected Exposure - EE

```
EE = mean(positive scenario exposures)
```

Reported per counterparty and for the portfolio.

### Potential Future Exposure - PFE

```
PFE 95% = 95th percentile of scenario exposure
PFE 99% = 99th percentile of scenario exposure
```

Portfolio PFE is the percentile of the *portfolio* distribution (the sum of
counterparty exposures within each scenario). It is lower than the sum of counterparty
PFEs because counterparties do not all reach their worst scenario on the same day; both
figures are reported.

### Collateral (`ccr/collateral.py`)

```
Collateral Requirement = max(Exposure - Threshold, 0)
Shortfall              = Requirement - Collateral Held
Transfer               = Shortfall   if |Shortfall| >= Minimum Transfer Amount, else 0
```

A positive transfer is a collateral **call**, a negative one a **return** of excess.

### Initial Margin (`ccr/margin.py`)

```
IM = Z x Volatility x Exposure x sqrt(T)
```

* `Z` - one-sided normal quantile of the confidence level (99% -> 2.326)
* `Volatility` - daily historical volatility of the trade's risk factor
* `Exposure` - delta-equivalent exposure, `Sensitivity x Notional`
* `T` - margin period of risk in days (10)

Calculated at trade, counterparty x risk factor, counterparty and portfolio level.
Within one counterparty, long and short positions in the same risk factor offset
(`net_within_risk_factor`); margins are then **added** across risk factors with no
diversification benefit. The contribution of each product / risk factor to total IM is
reported.

### Credit-limit monitoring (`ccr/limits.py`)

```
Exposure Utilisation = Net Exposure / Credit Limit
PFE Utilisation      = PFE 99% / Credit Limit
Utilisation          = max(Exposure Utilisation, PFE Utilisation)
```

| Status | Rule |
|---|---|
| Normal | utilisation below the counterparty's warning threshold |
| Warning | at or above the warning threshold, up to the limit |
| Breach | utilisation above 100% |

The monitor also reports the largest exposure, highest PFE, highest utilisation and the
largest day-on-day increase in exposure.

### Counterparty financial analysis (`ccr/credit_analysis.py`)

| Ratio | Formula |
|---|---|
| Debt / EBITDA | Total Debt / EBITDA |
| Current Ratio | Current Assets / Current Liabilities |
| Net Margin | Net Income / Revenue |
| Debt / Assets | Total Debt / Total Assets |
| Revenue Growth | (Revenue - Previous Revenue) / Previous Revenue |

**Internal credit risk score (0-100, higher = riskier).** Each ratio is mapped linearly
onto 0-100 risk points between a configured `best` and `worst` value (clipped), then
combined with configured weights:

```
risk points = clip((ratio - best) / (worst - best), 0, 1) x 100
score       = sum(weight x risk points)
```

| Ratio | Weight | Best (0 pts) | Worst (100 pts) |
|---|---|---|---|
| Debt / EBITDA | 30% | 1.0x | 6.0x |
| Current Ratio | 20% | 2.0x | 0.8x |
| Net Margin | 20% | 20% | 0% |
| Debt / Assets | 20% | 15% | 70% |
| Revenue Growth | 10% | +15% | -10% |

Categories: Low (<= 30), Moderate (<= 50), Elevated (<= 70), High (> 70). The points
behind every score are shown in the dashboard and the Excel report.

> This is an internal analytical score built for this project. It is not an agency
> rating or a probability of default.

### Daily risk commentary (`ccr/commentary.py`)

Commentary is generated from the numbers, comparing today's run with the previous
business day: changes in exposure, PFE, collateral and Initial Margin, limit breaches
and warnings, collateral calls, and weak financial metrics. The previous day's position
is derived by re-running the engine on the prior date with trade MTMs rolled back by the
latest one-day market move.

---

## 2. Architecture

```
risk-monitor/
├── app.py                  Streamlit entry point
├── run_pipeline.py         Command-line entry point
├── config/config.toml      All model parameters
├── ccr/                    Calculation package (no UI code)
│   ├── config.py           Typed, validated configuration
│   ├── market_data.py      Download / load history, returns, volatility, scenarios
│   ├── data_generation.py  Synthetic counterparties, trades, financials
│   ├── exposure.py         Scenario MTM, exposure distribution, EE, PFE
│   ├── collateral.py       Requirement, MTA, net exposure
│   ├── margin.py           Parametric Initial Margin
│   ├── limits.py           Utilisation, status, breach monitoring
│   ├── credit_analysis.py  Financial ratios and internal score
│   ├── commentary.py       Daily risk commentary
│   ├── pipeline.py         Orchestration (RiskSnapshot / RiskResults)
│   ├── database.py         SQLite persistence and named queries
│   └── reporting.py        Excel report and CSV extracts
├── dashboard/              Streamlit pages, UI components, Plotly charts, theme
├── sql/                    schema.sql, queries.sql
├── scripts/                fetch_market_data.py, generate_data.py
├── data/                   Input CSVs, market history, risk.db
├── reports/                Risk_Report.xlsx, latest/*.csv, vba/RefreshRiskReport.bas
└── tests/                  pytest suite
```

### Data flow

```
data/market/market_data.csv ──┐
data/trades.csv ──────────────┼─> pipeline.compute_snapshot (today and previous day)
data/counterparties.csv ──────┤      scenarios -> scenario MTM -> exposure distribution
data/financials.csv ──────────┘      -> EE / PFE -> collateral -> IM -> limits
                                              │
                    credit_analysis ──────────┤
                                              v
                                        RiskResults
                          ┌───────────────────┼────────────────────┐
                          v                   v                    v
                  data/risk.db        Streamlit dashboard   Risk_Report.xlsx
                  (SQL queries)                             + reports/latest/*.csv
```

The dashboard, database and Excel report all read the same `RiskResults` object, so a
number shown in one place matches the others and can be traced back through the scenario
matrix to the trade, sensitivity and market move that produced it.

### Database schema

| Table | Key | Contents |
|---|---|---|
| `counterparties` | `counterparty_id` | name, sector, country, rating, credit limit, warning threshold, collateral terms |
| `trades` | `trade_id` | counterparty, product, underlying, risk factor, notional, currency, maturity, MTM, sensitivity, volatility |
| `market_data` | `date, risk_factor` | level and daily return |
| `financials` | `counterparty_id` | revenue, EBITDA, net income, assets, debt, cash, current assets / liabilities, previous revenue |
| `credit_scores` | `counterparty_id` | five ratios, internal score, risk category |
| `exposure_results` | `run_date, counterparty_id` | current, gross, collateral, net, EE, PFE 95, PFE 99 |
| `exposure_scenarios` | `run_date, scenario_date, counterparty_id` | full exposure distribution |
| `margin_results` | `run_date, level, ...` | IM at trade / counterparty x factor / counterparty / portfolio level |
| `collateral_results` | `run_date, counterparty_id` | requirement, transfer, action, net exposure |
| `limit_breaches` | `run_date, counterparty_id` | limit, exposures, utilisations, status |
| `daily_commentary` | `run_date, sequence` | scope, severity, text |

Result tables hold both today's run and the previous business day's.

Named queries in `sql/queries.sql`:

| Key | Question |
|---|---|
| `limit_breaches` | Counterparties exceeding their credit limits |
| `above_warning` | Counterparties above the warning threshold |
| `highest_pfe` | Highest PFE |
| `highest_exposure` | Highest exposure |
| `exposure_by_sector` | Exposure by sector |
| `average_exposure_by_sector` | Average exposure by sector |
| `highest_initial_margin` | Highest Initial Margin |
| `elevated_credit_risk` | Counterparties with elevated credit-risk scores |
| `high_exposure_and_credit_risk` | Counterparties with both high exposure and elevated credit risk |

---

## 3. Installation

Requires Python 3.11 or later (`tomllib`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Running the application

**Full risk run** - calculations, SQLite, CSV extracts and the Excel report:

```bash
python run_pipeline.py
python run_pipeline.py --as-of 2026-09-15     # historical valuation date
```

**Dashboard:**

```bash
streamlit run app.py
```

Pages: Overview, Counterparty Risk, Exposure Analysis, Limit Monitoring, Credit Analysis,
Margin & Collateral, Market Data and Reports (report generation, exports, daily commentary
and SQL queries). Navigation is Streamlit's page router (one sidebar link per page, e.g. `/limits`,
`/counterparty?cp=CP003`); counterparty IDs in any table open that counterparty's risk profile. *Re-run analysis* in the sidebar
reloads the config and data, recomputes, and rewrites the database and report.

The UI layer is split into `dashboard/theme.py` (design tokens, stylesheet, Plotly style),
`dashboard/components.py` (navigation item, page and section headers, KPI cards, badges, tables,
metric rows, chart containers, banners, empty state, commentary box),
`dashboard/charts.py` (figure builders) and `dashboard/views.py` (pages).

**SQL:**

```bash
python run_pipeline.py --list-queries
python run_pipeline.py --query limit_breaches
sqlite3 data/risk.db
```

**Data:**

```bash
python scripts/fetch_market_data.py    # refresh market history from Yahoo Finance
python scripts/generate_data.py        # regenerate the synthetic portfolio (seeded)
```

**Excel report** - `reports/Risk_Report.xlsx` has nine sheets: Dashboard,
Counterparties, Exposure, PFE, Initial Margin, Collateral, Credit Analysis,
Limit Breaches and Daily Commentary, with Normal / Warning / Breach conditional
formatting. To refresh it from inside Excel, save it as `Risk_Report.xlsm`, import
`reports/vba/RefreshRiskReport.bas` (Alt+F11 -> File -> Import File) and run the
`RefreshRiskReport` macro: it reloads each sheet from the CSVs that the latest Python
run wrote to `reports/latest/`.

### Configuration

All parameters are in `config/config.toml` and validated on load:

| Section | Parameters |
|---|---|
| `[market_data]` | lookback (number of scenarios), volatility window, return percentiles |
| `[exposure]` | scenario horizon, PFE confidence levels, gross / netted aggregation |
| `[initial_margin]` | confidence level, margin period, volatility source and overrides, netting |
| `[limits]` | warning threshold, breach threshold |
| `[collateral]` | default threshold, default minimum transfer amount |
| `[credit_score]` | weights, best / worst bounds, category cut-offs |
| `[commentary]` | materiality thresholds for commentary sentences |

Per-counterparty warning thresholds, collateral thresholds and MTAs in
`data/counterparties.csv` take precedence over the config defaults.

---

## 5. Example results

Valuation date 1 October 2026, 5 counterparties, 25 trades, 500 scenarios of 10-day moves.

| Portfolio | |
|---|---|
| Total current exposure | ₹67.6M |
| Total EE | ₹127.3M |
| Portfolio PFE 99% | ₹184.3M |
| Total Initial Margin | ₹295.7M |
| Total collateral | ₹77.5M |
| Limit breaches / warnings | 1 / 1 |

| Counterparty | Rating | Score | Net exposure | EE | PFE 99% | IM | Limit | Utilisation | Status |
|---|---|---|---|---|---|---|---|---|---|
| CP003 Blue Harbour Shipping | BB+ | 95 High | ₹0.9M | ₹30.0M | ₹52.5M | ₹56.9M | ₹50M | 105% | **Breach** |
| CP002 Suryodaya Steel & Power | BBB | 67 Elevated | ₹5.3M | ₹32.6M | ₹47.0M | ₹40.1M | ₹55M | 85% | **Warning** |
| CP005 Kaveri Pharma Exports | A | 12 Low | ₹9.1M | ₹19.0M | ₹45.0M | ₹66.1M | ₹60M | 75% | Normal |
| CP001 Meridian Infotech | AA | 5 Low | ₹11.6M | ₹38.8M | ₹62.2M | ₹75.6M | ₹100M | 62% | Normal |
| CP004 Northwind Energy | A- | 38 Moderate | ₹5.2M | ₹6.9M | ₹27.9M | ₹57.0M | ₹150M | 19% | Normal |

Initial Margin by product: FX Forwards 43%, Interest Rate Swaps 31%, Equity Options 26%.

Generated commentary for CP003:

> CP003's 99% PFE decreased from ₹56.7M to ₹52.5M following favourable market movements.
> Current exposure decreased from ₹20.0M to ₹17.1M. 99% PFE exceeds the ₹50M credit limit
> (105% utilisation), so the limit breach continues. Net exposure after ₹24.0M of
> collateral is ₹0.9M; ₹4.1M of excess collateral is returnable. [...] Internal credit
> score is 95/100 (High risk): revenue fell 11.2% year on year, leverage is high at 10.4x
> Debt/EBITDA, the net margin is negative (-1.5%), the current ratio is below 1.0 (0.84x).

---

## 6. Testing

```bash
pytest
```

74 tests cover exposure, collateral, EE, PFE, Initial Margin, utilisation, breach
detection, financial ratios, the credit score, market-data statistics and an end-to-end
pipeline run. Properties asserted include:

* PFE 99% >= PFE 95%
* higher exposure -> higher IM
* higher volatility -> higher IM
* higher collateral -> lower net exposure
* exposure above the credit limit -> Breach

---

## 7. Data

* **Market data is real.** Five years of daily closes from Yahoo Finance: NIFTY 50
  (`^NSEI`), USD/INR (`INR=X`) and the US 10-year Treasury yield (`^TNX`). The file and
  its provenance are in `data/market/`. If the download is unavailable on first run, the
  pipeline falls back to a seeded synthetic history and records `source: synthetic` in
  the metadata file, which the dashboard displays.
* **Counterparties, trades and financials are synthetic**, generated with a fixed seed.
  The names are invented and do not refer to real companies.

## 8. Model assumptions and limitations

This is a transparent, sensitivity-based model, not a production exposure engine.

1. **Linear revaluation.** MTM changes are first-order (`Sensitivity x Shock x Notional`).
   Option gamma and vega, swap convexity and cross-gamma are ignored, so exposure on
   options is misstated for large moves.
2. **Single horizon.** EE and PFE are measured at one horizon (10 days), not as a profile
   over the life of the trades. There is no ageing, cash-flow or maturity roll-off.
3. **Interest-rate proxy.** INR swaps are shocked with changes in the US 10-year Treasury
   yield, because a free daily INR swap curve was not available. One point on one curve
   stands in for the whole INR curve, so curve shape and INR/USD rate basis are not
   captured.
4. **One risk factor per trade.** FX forwards carry no interest-rate risk and equity
   options no volatility risk.
5. **Overlapping scenarios.** The 500 ten-day moves overlap and are therefore
   autocorrelated; the effective number of independent scenarios is much smaller, and the
   99th percentile rests on about five observations.
6. **Historical simulation.** The future is assumed to resemble the last 500 trading
   days; scenarios are equally weighted with no volatility scaling or stress period.
7. **Collateral.** Collateral is cash in the base currency, with no haircuts, and is held
   constant across scenarios; PFE is therefore measured before collateral, and limit
   utilisation uses uncollateralised PFE. This is conservative.
8. **Initial Margin.** Normal-distribution multiplier with square-root-of-time scaling,
   applied to delta exposure. Margins add across risk factors without diversification,
   which is why total IM exceeds portfolio PFE. This is not ISDA SIMM.
9. **Netting.** Exposure distributions are gross by default (no netting agreement
   assumed); `aggregation = "netted"` is available.
10. **Previous-day comparison.** Yesterday's MTMs are implied by rolling today's back
    through the latest one-day market move; there is no stored trade history.
11. **Credit score.** A linear, weighted ratio score on one year of synthetic financials.
    It is not calibrated to default data.
12. **No wrong-way risk, CVA or default probabilities.**
