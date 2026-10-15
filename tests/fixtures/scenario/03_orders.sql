CREATE TABLE staging.orders AS SELECT o.order_id,o.customer_id,o.total FROM raw.orders o;
CREATE VIEW mart.orders AS SELECT order_id,total FROM staging.orders;
