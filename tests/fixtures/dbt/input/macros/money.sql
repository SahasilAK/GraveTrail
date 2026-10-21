{% macro money(x) %}{{ scale(x) }}{% endmacro %}
{% macro scale(x) %}{{ x }}/100{% endmacro %}
