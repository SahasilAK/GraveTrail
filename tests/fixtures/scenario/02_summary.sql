CREATE TABLE mart.customer_summary AS
WITH active_customers AS (
    SELECT c.customer_id, c.customer_name
    FROM staging.customers c
    WHERE c.active = 1
)
SELECT customer_id, customer_name FROM active_customers;
