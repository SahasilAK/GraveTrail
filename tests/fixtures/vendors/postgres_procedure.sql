-- Definition dependencies do not prove this procedure was called.
CREATE OR REPLACE PROCEDURE mart.refresh_orders()
LANGUAGE SQL
AS $body$
INSERT INTO mart.orders (id, amount)
SELECT id, amount FROM raw.orders WHERE active = true;
INSERT INTO mart.order_audit (id)
SELECT id FROM mart.orders;
$body$;
