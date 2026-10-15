MERGE INTO mart.orders t USING raw.orders s ON (t.id = s.id)
WHEN MATCHED THEN UPDATE SET t.amount = s.amount;
CREATE OR REPLACE VIEW mart.active_orders AS
SELECT o.id, o.amount FROM mart.orders o WHERE o.active = 1;
