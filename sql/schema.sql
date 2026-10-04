-- Counterparty Credit Risk & Exposure Analytics - SQLite schema
-- Amounts are in the base currency (INR) unless a column says otherwise.

CREATE TABLE IF NOT EXISTS counterparties (
    counterparty_id         TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    sector                  TEXT NOT NULL,
    country                 TEXT NOT NULL,
    credit_rating           TEXT NOT NULL,
    credit_limit            REAL NOT NULL CHECK (credit_limit > 0),
    warning_threshold       REAL NOT NULL,
    collateral              REAL NOT NULL DEFAULT 0,
    collateral_threshold    REAL NOT NULL DEFAULT 0,
    minimum_transfer_amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id        TEXT PRIMARY KEY,
    counterparty_id TEXT NOT NULL REFERENCES counterparties (counterparty_id),
    product_type    TEXT NOT NULL,
    underlying      TEXT NOT NULL,
    risk_factor     TEXT NOT NULL,
    notional        REAL NOT NULL,          -- in trade currency
    currency        TEXT NOT NULL,
    maturity        TEXT NOT NULL,
    current_mtm     REAL NOT NULL,          -- base currency
    sensitivity     REAL NOT NULL,
    volatility      REAL NOT NULL           -- annualised
);

CREATE TABLE IF NOT EXISTS market_data (
    date         TEXT NOT NULL,
    risk_factor  TEXT NOT NULL,
    value        REAL NOT NULL,
    daily_return REAL,                      -- relative return, or yield change as a decimal
    PRIMARY KEY (date, risk_factor)
);

CREATE TABLE IF NOT EXISTS financials (
    counterparty_id     TEXT PRIMARY KEY REFERENCES counterparties (counterparty_id),
    fiscal_year         TEXT,
    revenue             REAL NOT NULL,
    ebitda              REAL NOT NULL,
    net_income          REAL NOT NULL,
    total_assets        REAL NOT NULL,
    total_debt          REAL NOT NULL,
    cash                REAL NOT NULL,
    current_assets      REAL NOT NULL,
    current_liabilities REAL NOT NULL,
    previous_revenue    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS credit_scores (
    counterparty_id TEXT PRIMARY KEY REFERENCES counterparties (counterparty_id),
    debt_to_ebitda  REAL,
    current_ratio   REAL,
    net_margin      REAL,
    debt_to_assets  REAL,
    revenue_growth  REAL,
    credit_score    REAL NOT NULL,          -- internal analytical score, 0 = low risk, 100 = high risk
    risk_category   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exposure_results (
    run_date          TEXT NOT NULL,
    counterparty_id   TEXT NOT NULL REFERENCES counterparties (counterparty_id),
    current_exposure  REAL NOT NULL,
    gross_exposure    REAL NOT NULL,
    collateral        REAL NOT NULL,
    net_exposure      REAL NOT NULL,
    expected_exposure REAL NOT NULL,
    pfe_95            REAL,
    pfe_99            REAL,
    PRIMARY KEY (run_date, counterparty_id)
);

CREATE TABLE IF NOT EXISTS exposure_scenarios (
    run_date        TEXT NOT NULL,
    scenario_date   TEXT NOT NULL,
    counterparty_id TEXT NOT NULL,
    exposure        REAL NOT NULL,
    PRIMARY KEY (run_date, scenario_date, counterparty_id)
);

-- level = 'trade' | 'counterparty_factor' | 'counterparty' | 'portfolio'
CREATE TABLE IF NOT EXISTS margin_results (
    run_date        TEXT NOT NULL,
    level           TEXT NOT NULL,
    counterparty_id TEXT,
    trade_id        TEXT,
    product_type    TEXT,
    risk_factor     TEXT,
    delta_exposure  REAL,
    daily_volatility REAL,
    initial_margin  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS collateral_results (
    run_date                TEXT NOT NULL,
    counterparty_id         TEXT NOT NULL REFERENCES counterparties (counterparty_id),
    gross_exposure          REAL NOT NULL,
    collateral_held         REAL NOT NULL,
    collateral_threshold    REAL NOT NULL,
    minimum_transfer_amount REAL NOT NULL,
    collateral_requirement  REAL NOT NULL,
    transfer_amount         REAL NOT NULL,
    action                  TEXT NOT NULL,
    net_exposure            REAL NOT NULL,
    PRIMARY KEY (run_date, counterparty_id)
);

-- One row per counterparty and run; status = 'Normal' | 'Warning' | 'Breach'
CREATE TABLE IF NOT EXISTS limit_breaches (
    run_date             TEXT NOT NULL,
    counterparty_id      TEXT NOT NULL REFERENCES counterparties (counterparty_id),
    credit_limit         REAL NOT NULL,
    warning_threshold    REAL NOT NULL,
    current_exposure     REAL NOT NULL,
    net_exposure         REAL NOT NULL,
    pfe                  REAL NOT NULL,
    exposure_utilisation REAL NOT NULL,
    pfe_utilisation      REAL NOT NULL,
    utilisation          REAL NOT NULL,
    status               TEXT NOT NULL,
    PRIMARY KEY (run_date, counterparty_id)
);

CREATE TABLE IF NOT EXISTS daily_commentary (
    run_date TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    scope    TEXT NOT NULL,
    severity TEXT NOT NULL,
    text     TEXT NOT NULL,
    PRIMARY KEY (run_date, sequence)
);

CREATE INDEX IF NOT EXISTS idx_trades_counterparty ON trades (counterparty_id);
CREATE INDEX IF NOT EXISTS idx_limit_status ON limit_breaches (run_date, status);
