"""rka.skills namespace.

Role-specific skill content lives as .md files under brain/, executor/, pi/,
and writer/ subdirectories. Phase 2 added writer/mcp_tools/ as a Python
subpackage for the rka-writer-tools combined MCP server.

This __init__.py exists so rka.skills.writer.mcp_tools.* is importable as a
regular Python package. Skill markdown files remain accessible as package
data via the rka [tool.setuptools.package-data] declaration in pyproject.toml.
"""
