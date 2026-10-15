CREATE OR REPLACE TEMPORARY TABLE stage AS
SELECT o.id, o.amount FROM raw.orders o
QUALIFY ROW_NUMBER() OVER (PARTITION BY o.id ORDER BY o.changed_at DESC) = 1;
MERGE INTO mart.orders t USING stage s ON t.id = s.id
WHEN MATCHED THEN UPDATE SET amount = s.amount;
