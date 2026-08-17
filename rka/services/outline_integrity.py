"""Pure hierarchy validation shared by manuscript writes and pack imports."""

from __future__ import annotations

from typing import Any


def validate_unit_hierarchy(units: list[dict[str, Any]]) -> None:
    """Validate one manuscript's canonical flat-tree representation.

    ``local_key`` is the stable node key, ``parent_unit_key`` names another
    node, and ``sequence`` stores the depth-first flat order. Removed nodes may
    remain for provenance but cannot parent active nodes.
    """

    by_key = {unit["local_key"]: unit for unit in units}
    for unit in units:
        parent_key = unit.get("parent_unit_key")
        if parent_key is None:
            continue
        parent = by_key.get(parent_key)
        if parent is None:
            raise ValueError(f"unit {unit['local_key']} references unknown parent {parent_key!r}")
        if parent_key == unit["local_key"]:
            raise ValueError("outline unit cannot be its own parent")
        if parent.get("status") == "removed" and unit.get("status") != "removed":
            raise ValueError(f"active unit {unit['local_key']} cannot have a removed parent")

    # Report cycles independently of depth so a corrupt import receives the
    # causal failure instead of an incidental level error.
    for unit in units:
        seen = {unit["local_key"]}
        cursor = unit
        while cursor.get("parent_unit_key") is not None:
            key = str(cursor["parent_unit_key"])
            if key in seen:
                raise ValueError("outline hierarchy contains a cycle")
            if key not in by_key:
                raise ValueError(f"unit {cursor['local_key']} references unknown parent {key!r}")
            seen.add(key)
            cursor = by_key[key]

    for unit in units:
        parent_key = unit.get("parent_unit_key")
        if parent_key is None:
            continue
        parent = by_key[str(parent_key)]
        if int(parent["outline_level"]) >= int(unit["outline_level"]):
            raise ValueError(
                f"parent {parent_key} must be at a shallower outline depth than "
                f"child {unit['local_key']}"
            )

    active_with_index = [
        (index, unit) for index, unit in enumerate(units) if unit.get("status") != "removed"
    ]
    active = [
        unit
        for _index, unit in sorted(
            active_with_index,
            key=lambda item: (int(item[1]["sequence"]), item[0]),
        )
    ]
    positions = {unit["local_key"]: index for index, unit in enumerate(active)}
    active_parents = {unit["local_key"]: unit.get("parent_unit_key") for unit in active}

    def descendants(root: str) -> set[str]:
        found: set[str] = set()
        frontier = [root]
        while frontier:
            current = frontier.pop()
            for child, parent in active_parents.items():
                if parent == current and child not in found:
                    found.add(child)
                    frontier.append(child)
        return found

    for key, parent_key in active_parents.items():
        if parent_key is not None and positions[parent_key] >= positions[key]:
            raise ValueError(f"outline order must place parent {parent_key!r} before child {key!r}")
    for key in positions:
        nested = descendants(key)
        if not nested:
            continue
        occupied = {positions[key], *(positions[item] for item in nested)}
        if max(occupied) - min(occupied) + 1 != len(occupied):
            raise ValueError(f"outline order must keep subtree {key!r} contiguous")
