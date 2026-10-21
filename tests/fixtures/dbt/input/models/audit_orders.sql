{{ config(materialized='incremental') }}
select order_id, amount from {{ ref('fct_orders') }}
