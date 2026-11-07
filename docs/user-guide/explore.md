# Explore lineage and change impact

Open **Lineage**, search and select the exact qualified asset identity.

1. Choose upstream for inputs, downstream for consumers, or combined for both.
2. Open **Traversal options** to set depth and temporary-step collapsing.
3. Choose **Graph** for an overview or **Tree** to expand paths progressively.
4. Select a node/relationship to narrow source evidence.
5. For change impact, inspect downstream consumers and their original code.

![SQL sample explored upstream at depth 30](../assets/images/gravetrail-lineage-explorer.png)

*Layout order is not execution order.*

Use Fit, zoom, pan, search and Fullscreen in the graph toolbar. Double-click a node
or focus it and press **Alt+Enter** to navigate. **Back**/**Forward** restore asset
views in the session. Tree mode requires an exact asset.

**All** includes disconnected assets and bypasses focused traversal limits; confidence
and temporary filters still apply. A truncated graph/tree is not proof of no further
dependencies. Cycles stop at repeated nodes. Check schema/job/dbt version for similar names.

For dbt, expand **dbt resources and macro impact** to inspect typed relationships
separately from the model graph. See [dbt resources](../DBT_SUPPORT.md#models-columns-and-resources).

Continue with [evidence](evidence.md), [exports](exports.md) or the [UI reference](../USER_GUIDE.md).
