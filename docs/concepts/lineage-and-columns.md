# Table lineage, column usage and transformations

**Table lineage** connects inputs to outputs. Upstream follows inputs; downstream
follows consumers. The same short name can identify different schemas, temporary
jobs or versioned dbt assets. Select an exact identity.

**Direct column usage** records references and contexts. It answers where a name
appears, including supported join/filter/projection contexts. It does not by itself
establish how an output value is calculated.

**Transformation lineage** represents supported output expressions and input roles.
Value inputs, CASE selection, join/filter context, rowsets and window partition/order
are distinct. Unsupported expressions remain boundaries instead of guessed derivations.

For example, `SUM(amount)` uses amount values and a contributing rowset; `COUNT(*)`
depends on a rowset without claiming a particular column value. A WHERE condition
affects which rows contribute rather than being copied into every output.

Temporary-step collapsing simplifies a view while retaining intermediate evidence.
It does not prove the intermediate never exists at runtime. Cycles terminate traversal;
depth, node caps and response pagination can bound results. Logical paths are not
executable job schedules.

Use [exploration](../user-guide/explore.md), [columns](../user-guide/columns.md) and
the exact [transformation coverage reference](../TRANSFORMATION_LINEAGE.md).
