-- Named risk queries. Each block starts with "-- name: <key> | <title>".
-- :elevated_score and :high_utilisation are bound from config by ccr.database.run_query.
-- All queries read the latest run in the database.

-- name: limit_breaches | Counterparties exceeding their credit limits
SELECT l.counterparty_id, c.name, l.credit_limit, l.net_exposure, l.pfe,
       ROUND(l.utilisation * 100, 1) AS utilisation_pct, l.status
FROM limit_breaches l
JOIN counterparties c USING (counterparty_id)
WHERE l.run_date = (SELECT MAX(run_date) FROM limit_breaches)
  AND l.status = 'Breach'
ORDER BY l.utilisation DESC;

-- name: above_warning | Counterparties above the warning threshold
SELECT l.counterparty_id, c.name, l.credit_limit,
       ROUND(l.warning_threshold * 100, 0) AS warning_pct,
       ROUND(l.utilisation * 100, 1) AS utilisation_pct, l.status
FROM limit_breaches l
JOIN counterparties c USING (counterparty_id)
WHERE l.run_date = (SELECT MAX(run_date) FROM limit_breaches)
  AND l.utilisation >= l.warning_threshold
ORDER BY l.utilisation DESC;

-- name: highest_pfe | Highest PFE
SELECT e.counterparty_id, c.name, e.pfe_95, e.pfe_99, e.expected_exposure
FROM exposure_results e
JOIN counterparties c USING (counterparty_id)
WHERE e.run_date = (SELECT MAX(run_date) FROM exposure_results)
ORDER BY e.pfe_99 DESC;

-- name: highest_exposure | Highest exposure
SELECT e.counterparty_id, c.name, e.current_exposure, e.gross_exposure, e.collateral, e.net_exposure
FROM exposure_results e
JOIN counterparties c USING (counterparty_id)
WHERE e.run_date = (SELECT MAX(run_date) FROM exposure_results)
ORDER BY e.gross_exposure DESC;

-- name: exposure_by_sector | Exposure by sector
SELECT c.sector,
       COUNT(*) AS counterparties,
       SUM(e.current_exposure) AS current_exposure,
       SUM(e.gross_exposure) AS gross_exposure,
       SUM(e.net_exposure) AS net_exposure,
       SUM(e.pfe_99) AS pfe_99
FROM exposure_results e
JOIN counterparties c USING (counterparty_id)
WHERE e.run_date = (SELECT MAX(run_date) FROM exposure_results)
GROUP BY c.sector
ORDER BY gross_exposure DESC;

-- name: average_exposure_by_sector | Average exposure by sector
SELECT c.sector,
       COUNT(*) AS counterparties,
       AVG(e.gross_exposure) AS average_gross_exposure,
       AVG(e.net_exposure) AS average_net_exposure,
       AVG(e.pfe_99) AS average_pfe_99
FROM exposure_results e
JOIN counterparties c USING (counterparty_id)
WHERE e.run_date = (SELECT MAX(run_date) FROM exposure_results)
GROUP BY c.sector
ORDER BY average_gross_exposure DESC;

-- name: highest_initial_margin | Highest Initial Margin
SELECT m.counterparty_id, c.name, m.initial_margin
FROM margin_results m
JOIN counterparties c USING (counterparty_id)
WHERE m.run_date = (SELECT MAX(run_date) FROM margin_results)
  AND m.level = 'counterparty'
ORDER BY m.initial_margin DESC;

-- name: elevated_credit_risk | Counterparties with elevated credit-risk scores
SELECT s.counterparty_id, c.name, c.sector, c.credit_rating,
       ROUND(s.credit_score, 1) AS credit_score, s.risk_category
FROM credit_scores s
JOIN counterparties c USING (counterparty_id)
WHERE s.credit_score > :elevated_score
ORDER BY s.credit_score DESC;

-- name: high_exposure_and_credit_risk | Counterparties with both high exposure and elevated credit risk
SELECT l.counterparty_id, c.name, c.sector,
       ROUND(s.credit_score, 1) AS credit_score, s.risk_category,
       l.net_exposure, l.pfe, ROUND(l.utilisation * 100, 1) AS utilisation_pct, l.status
FROM limit_breaches l
JOIN counterparties c USING (counterparty_id)
JOIN credit_scores s USING (counterparty_id)
WHERE l.run_date = (SELECT MAX(run_date) FROM limit_breaches)
  AND s.credit_score > :elevated_score
  AND l.utilisation >= :high_utilisation
ORDER BY l.utilisation DESC;
