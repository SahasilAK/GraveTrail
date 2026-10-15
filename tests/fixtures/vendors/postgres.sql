CREATE TEMPORARY TABLE stage AS
WITH picked AS (SELECT o.id, o.amount FROM raw.orders o WHERE o.active = true)
SELECT id, amount FROM picked;
INSERT INTO mart.orders SELECT id, amount FROM stage;
DELETE FROM mart.orders USING raw.cancelled c WHERE mart.orders.id = c.id;
