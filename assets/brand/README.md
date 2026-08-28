# RKA Project visual identity

This directory is the source of truth for the shared visual identity used by
RKA Core and other RKA Project products. The mark represents a durable research
record (the vertical spine) branching into structured knowledge and exploration
(teal) and salient evidence, decisions, or outputs (amber).

## Production masters

| File | Intended use |
|---|---|
| `rka-project-mark-color.svg` | General-purpose color mark on light backgrounds. |
| `rka-project-mark-monochrome.svg` | One-color contexts; set the CSS `color` property when embedding inline. |
| `rka-project-plugin-app-icon.svg` | Browser, plugin, and app surfaces on either light or dark backgrounds. |
| `rka-brand-tokens.css` | Shared color values for deterministic exports. |

The Web and Claude-plugin copies of the app icon are release mirrors. Tests
require them to remain byte-for-byte identical to the master in this directory.

## Reference compositions

`rka-project-wordmark-horizontal.svg` and `rka-project-lockup-dark.svg` preserve
the approved composition, spacing, and type direction. They currently contain
live text using a system-font fallback stack, so they are design references—not
portable production masters. Convert the lettering to vector outlines after the
final typeface is approved before using either file as a release asset.

## Usage notes

- Keep the product name as real text beside the symbol for accessibility and
  searchability. In this repository, the visible product name is **RKA Core**;
  **RKA Project** is the broader ecosystem identity.
- Use the app icon when the background is unknown. The transparent color mark's
  navy spine can disappear on dark surfaces.
- Teal and amber are structural accent colors in the symbol. Do not use them as
  small body text on white or off-white backgrounds.
- Do not stretch, rotate, recolor individual branches, or add effects to the
  masters.
- Generate raster sizes deterministically from these SVG masters. The original
  concept PNGs are intentionally not committed as production exports.

These assets are distributed under the repository's [MIT license](../../LICENSE).
