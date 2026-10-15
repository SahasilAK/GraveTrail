CREATE OR REPLACE TABLE `analytics.mart.orders` AS
WITH picked AS (
  SELECT o.id, o.amount FROM `analytics.raw.orders` o WHERE o.active = true
)
SELECT id, amount FROM picked;
