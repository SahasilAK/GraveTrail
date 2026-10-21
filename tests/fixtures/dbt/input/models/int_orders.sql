{{ config(materialized='ephemeral') }}
select order_id, customer_id, amount * 2 as doubled from {{ ref('stg_orders') }}
