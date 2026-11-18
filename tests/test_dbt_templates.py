

def test_multiple_macros_and_dbt_custom_blocks_do_not_execute():
    from dataforge.dbt.templates import scan_template
    facts = scan_template('''{% macro a(x) %}{{ b(x) }}{% endmacro %}
{% macro b(x) %}{{ run_query('delete from secret') }}{% endmacro %}
{% snapshot s %}select * from {{ ref('orders') }}{% endsnapshot %}
''')
    assert {m.name for m in facts.definitions} == {'a', 'b', 's'}
    assert any(c.name == 'run_query' for c in facts.calls)
