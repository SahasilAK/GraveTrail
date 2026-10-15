CREATE VOLATILE TABLE stage AS (
  SELECT id, amount FROM raw.orders
) WITH DATA ON COMMIT PRESERVE ROWS;
INSERT INTO mart.orders SELECT id, amount FROM stage;
