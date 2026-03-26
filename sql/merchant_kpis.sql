-- Merchant KPI query for the Command Center dashboard.
-- Replace the FROM/JOIN and column names with your real Affirm Snowflake objects.
-- Expected result columns (aliases must match):
--   merchant_name   — string, matches merchant names from the managed-merchant list
--   num_applications — number of applications (or NULL)
--   approval_rate    — decimal 0–100 or 0–1 (displayed as %)
--   take_rate          — decimal (displayed as %)
--   loans              — count or volume of loans
--   aov                — average order value (currency units)

-- The app injects: WHERE merchant_name IN ('Name1','Name2',...)
-- If you prefer a single summary table keyed by merchant, keep the WHERE clause pattern.

SELECT
  m.merchant_name       AS merchant_name,
  m.num_applications    AS num_applications,
  m.approval_rate       AS approval_rate,
  m.take_rate           AS take_rate,
  m.loans               AS loans,
  m.aov                 AS aov
FROM (
  -- TODO: replace with your schema, e.g. affirm_dw.analytics.merchant_kpis_monthly
  SELECT
    'Example Merchant' AS merchant_name,
    NULL::NUMBER       AS num_applications,
    NULL::FLOAT        AS approval_rate,
    NULL::FLOAT        AS take_rate,
    NULL::NUMBER       AS loans,
    NULL::FLOAT        AS aov
  WHERE 1 = 0
) AS m
WHERE m.merchant_name IN ({MERCHANT_IN})
