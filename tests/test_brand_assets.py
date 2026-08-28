"""Regression checks for the RKA Project visual identity contract."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
BRAND_ROOT = ROOT / "assets" / "brand"
APP_ICON = BRAND_ROOT / "rka-project-plugin-app-icon.svg"
SVG_ASSETS = (
    BRAND_ROOT / "rka-project-mark-color.svg",
    BRAND_ROOT / "rka-project-mark-monochrome.svg",
    APP_ICON,
    BRAND_ROOT / "rka-project-wordmark-horizontal.svg",
    BRAND_ROOT / "rka-project-lockup-dark.svg",
)
RUNTIME_ICON_MIRRORS = (
    ROOT / "web" / "public" / "brand" / "rka-project-plugin-app-icon.svg",
    ROOT / "plugin" / "assets" / "rka-project-plugin-app-icon.svg",
)
FORBIDDEN_SVG_ELEMENTS = {"script", "image", "foreignObject"}


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def test_brand_svg_assets_are_self_contained() -> None:
    for asset in SVG_ASSETS:
        root = ElementTree.parse(asset).getroot()
        assert _local_name(root.tag) == "svg"
        assert root.attrib.get("viewBox")

        for element in root.iter():
            assert _local_name(element.tag) not in FORBIDDEN_SVG_ELEMENTS
            for name, value in element.attrib.items():
                if _local_name(name) == "href":
                    assert not value.startswith(("http://", "https://", "//"))


def test_runtime_icons_match_the_canonical_master() -> None:
    canonical = APP_ICON.read_bytes()
    for mirror in RUNTIME_ICON_MIRRORS:
        assert mirror.read_bytes() == canonical


def test_web_identity_uses_the_runtime_icon_and_product_name() -> None:
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    sidebar = (
        ROOT / "web" / "src" / "components" / "layout" / "Sidebar.tsx"
    ).read_text(encoding="utf-8")

    icon_path = "/brand/rka-project-plugin-app-icon.svg"
    assert f'href="{icon_path}"' in index
    assert "<title>RKA Core — Research Knowledge Agent</title>" in index
    assert 'name="theme-color" content="#073566"' in index
    assert f'src="{icon_path}"' in sidebar
    assert 'alt=""' in sidebar


def test_readmes_keep_accessible_text_with_the_mark() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plugin_readme = (ROOT / "plugin" / "README.md").read_text(encoding="utf-8")

    assert "# RKA Core — Research Knowledge Agent" in root_readme
    assert (
        "https://raw.githubusercontent.com/infinitywings/rka/main/"
        "assets/brand/rka-project-plugin-app-icon.svg"
    ) in root_readme
    assert "# rka — Claude Code plugin for the Research Knowledge Agent" in plugin_readme
    assert "assets/rka-project-plugin-app-icon.svg" in plugin_readme
