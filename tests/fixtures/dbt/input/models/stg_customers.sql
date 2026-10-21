select id as customer_id, country_code, status from {{ source('raw', 'customers') }}
