# GrooveMap brand source

This directory owns the canonical editable GrooveMap brand. For repository ownership and contribution guidance, see the [repository README](../README.md). Use of the project name and logos is also subject to the separate [trademark-use policy](../TRADEMARKS.md); repository source is available under the [MIT License](../LICENSE).

`tokens.json` and `templates/` are the sources; `assets/` contains deterministic rendered SVG, manifest, and CSS outputs. Change sources once, run `just brand-render`, review the diff, and promote only generated files to `.github`, the Pages site, applications, or documentation.

The constellation-record geometry and Deep Space + Purple palette were migrated from the monorepo's `scripts/generate_brand_assets.py`. The product name and copy are now GrooveMap and `groovemap.music`.

## Reproduction

```sh
just brand-render
just brand
```

The renderer uses only pinned Node.js standard-library APIs. Given the same tracked inputs it produces byte-identical source assets. Consumers that require PNG or ICO outputs should add an explicitly pinned rasterizer and retain the SVG originals as provenance.

`assets.sha256` fixes the reviewed 12-file output set. `just brand` first renders in check mode and then verifies every output byte against that manifest.

## Font licensing

The source monorepo contained Space Grotesk TTF files without an adjacent OFL or other font notice. Those binaries are intentionally **not** promoted here. Current SVGs request a system font stack and embed no font software. Space Grotesk may be added only with verified provenance, its required license text, and a deterministic pinned rendering toolchain.
