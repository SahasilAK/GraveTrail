{% snapshot legacy_orders %}
select * from {{ source('raw', 'orders') }}
{% endsnapshot %}
