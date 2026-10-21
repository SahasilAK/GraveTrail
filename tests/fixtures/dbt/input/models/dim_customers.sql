{{ config(schema='dimensions', alias='customers') }}
select c.customer_id, n.country, s.status from {{ ref('stg_customers') }} c left join {{ ref('countries') }} n on c.country_code=n.code left join {{ ref('statuses') }} s on c.status=s.status
