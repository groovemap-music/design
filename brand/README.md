# GrooveMap brand source

See the infrastructure [documentation index](../docs/README.md) for design ownership.

This directory owns the canonical editable GrooveMap brand. `tokens.json` and `templates/` are the sources; `assets/` contains deterministic rendered SVG, manifest, and CSS outputs. Change sources once, run `just brand-render`, review the diff, and promote only generated files to `.github`, the Pages site, applications, or documentation.

The constellation-record geometry and Deep Space + Purple palette were migrated from the monorepo's `scripts/generate_brand_assets.py`. The product name and copy are now GrooveMap and `groovemap.music`.

`legacy/` retains the monorepo's original design-system document and showcase with their
source commit. They are historical references, not editable GrooveMap sources or promoted
build inputs; the current tokens and templates in this directory are authoritative.

## Reproduction

```sh
mise install
just brand-render
just brand
```

The renderer uses only pinned Node.js standard-library APIs. Given the same tracked inputs it produces byte-identical source assets. Consumers that require PNG or ICO outputs should add an explicitly pinned rasterizer and retain the SVG originals as provenance.

## Font licensing

The source monorepo contained Space Grotesk TTF files without an adjacent OFL or other font notice. Those binaries are intentionally **not** promoted here. Current SVGs request a system font stack and embed no font software. Space Grotesk may be added only with verified provenance, its required license text, and a deterministic pinned rendering toolchain.
