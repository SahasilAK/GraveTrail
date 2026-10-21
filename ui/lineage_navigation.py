"""Workspace-scoped lineage view history; only IDs and controls enter session state."""
from collections.abc import MutableMapping
from typing import Any

ALL_ASSETS = "all-assets"


def focus_asset(state: MutableMapping[str, Any], workspace: str, asset: str, name: str) -> None:
    """Record an asset as the next lineage focus in session state.

    Args:
        state: Session state mapping to update.
        workspace: Workspace identifier that scopes the selection.
        asset: Selected asset ID.
        name: Display name used to populate the search control.
    """
    state["asset_search_lineage"] = name
    state[f"asset_choice_lineage_{workspace}"] = asset
    state["exploration_asset_" + workspace] = asset
    state["lineage_view_" + workspace] = "Graph"
    for sibling in ("columns", "impact"):
        state.pop(f"asset_choice_{sibling}_{workspace}", None)


def remember_view(state: MutableMapping[str, Any], workspace: str, view: dict[str, Any]) -> dict[str, Any]:
    """Append or replace the current lineage view in bounded session history.

    Args:
        state: Session state mapping to update.
        workspace: Workspace identifier that scopes the history.
        view: View settings and focused asset to record.

    Returns:
        Workspace history mapping after the view is recorded.
    """
    history = state.setdefault("lineage_history_" + workspace, {"entries": [], "index": -1})
    entries, index = history["entries"], history["index"]
    if index >= 0 and entries[index]["asset"] == view["asset"]:
        entries[index] = view
    else:
        history["entries"] = entries[:index + 1] + [view]
        history["index"] = index + 1
    return history


def move_history(state: MutableMapping[str, Any], workspace: str, step: int) -> dict[str, Any] | None:
    """Move the selected workspace history index and return its view if present.

    Args:
        state: Session state mapping containing the history.
        workspace: Workspace identifier that scopes the history.
        step: Index offset, normally ``-1`` or ``1``.

    Returns:
        The view at the updated index, or ``None`` when history is unavailable.
    """
    history = state["lineage_history_" + workspace]
    index = history["index"] + step
    if not 0 <= index < len(history["entries"]):
        return
    history["index"] = index
    view = history["entries"][index]
    state["asset_search_lineage"] = view["query"]
    state[f"asset_choice_lineage_{workspace}"] = view["asset"]
    for prefix, field in [("graph_direction_", "direction"), ("graph_depth_", "depth"),
                          ("graph_collapse_", "simplified"), ("lineage_view_", "view")]:
        state[prefix + workspace] = view[field]
    state["lineage_direction_tabs"] = view["tree_direction"]
    state["lineage_evidence_direction_" + workspace] = view["tree_direction"]
    if view["asset"] != ALL_ASSETS:
        state["exploration_asset_" + workspace] = view["asset"]
        for sibling in ("columns", "impact"):
            state.pop(f"asset_choice_{sibling}_{workspace}", None)
