select o.order_id, o.customer_id, {{ money('o.doubled') }} as amount from {{ ref('int_orders') }} o join {{ ref('stg_customers') }} c on o.customer_id=c.customer_id
