-- Inspect literal SQL only; never execute it.
EXECUTE IMMEDIATE 'INSERT INTO mart.active_orders
SELECT id FROM raw.orders WHERE state = ''active''';
EXECUTE IMMEDIATE $$CREATE TABLE mart.order_totals AS
SELECT customer_id, SUM(amount) AS total FROM raw.orders GROUP BY customer_id;$$;
