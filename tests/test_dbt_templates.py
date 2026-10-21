def test_template_structure_distinguishes_calls_and_unknown_branches():
    from dataforge.dbt.templates import scan_template
    facts = scan_template('''{{ config(materialized='view') }}
select {{ pkg.money('amount') }} from {{ ref('orders', version=2) }}
{% if target.name == 'prod' %} join {{ source('raw', 'extra') }} e on true {% endif %}
-- {{ ref('fake') }}
select '{{ ref("also_fake") }}'
{# {{ ref('ignored') }} #}
''')
    assert [(c.name, c.args, c.conditional) for c in facts.calls if c.name in {'ref', 'source'}] == [
        ('ref', ('orders',), False), ('source', ('raw', 'extra'), True)]
    assert facts.config == {'materialized': 'view'}
    assert any(c.name == 'pkg.money' for c in facts.calls)


def test_multiple_macros_and_dbt_custom_blocks_do_not_execute():
    from dataforge.dbt.templates import scan_template
    facts = scan_template('''{% macro a(x) %}{{ b(x) }}{% endmacro %}
{% macro b(x) %}{{ run_query('delete from secret') }}{% endmacro %}
{% snapshot s %}select * from {{ ref('orders') }}{% endsnapshot %}
''')
    assert {m.name for m in facts.definitions} == {'a', 'b', 's'}
    assert any(c.name == 'run_query' for c in facts.calls)


def test_inline_condition_and_nested_macro_refs_are_candidates():
    from dataforge.dbt.templates import scan_template
    facts = scan_template("select * from {{ ref('base') if target.name == 'prod' else ref('other') }}")
    assert all(c.conditional for c in facts.calls if c.name == 'ref')
    nested = scan_template("select * from {{ ignore(ref('base')) }}")
    assert next(c for c in nested.calls if c.name == 'ref').conditional
