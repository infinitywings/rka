"""Repository-wide pytest ownership markers."""

from __future__ import annotations

import pytest

from tests.ownership import owner_for_test


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark frozen downstream tests while leaving Core as the default profile."""
    root = config.rootpath
    for item in items:
        try:
            relative_path = item.path.relative_to(root).as_posix()
        except ValueError:
            relative_path = item.path.as_posix()
        owner = owner_for_test(relative_path)
        if owner != "core":
            item.add_marker(getattr(pytest.mark, owner))
