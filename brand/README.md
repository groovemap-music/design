# GrooveMap brand source

This directory owns the canonical editable GrooveMap brand. For repository ownership and contribution guidance, see the [repository README](../README.md). Use of the project name and logos is also subject to the separate [trademark-use policy](../TRADEMARKS.md); repository source is available under the [MIT License](../LICENSE).

`tokens.json`, `templates/`, `mark.mjs`, and `fonts/` are the sources; `assets/` contains deterministic rendered SVG, manifest, and CSS outputs. Change sources once, run `just brand-render`, review the diff, and promote only generated files to `.github`, the Pages site, applications, or documentation.

The identity is the **Degrees** mark on the **Lagoon** palette, with a lowercase `groovemap` wordmark set in Jura. It replaces the constellation-record mark and the Deep Space + Purple palette that were migrated from the monorepo's `scripts/generate_brand_assets.py`.

- [`mark.mjs`](mark.mjs) draws the mark in a 100-unit box. A seed sits at the center, and each contour ring is one more degree of separation, with edges running outward ring by ring. The inner ring is a true circle and the outer rings drift into terrain contours. A pin on the outer ring marks the viewer's position. Favicons use a simplified variant with two rings and three nodes.
- `color.mint` is the dark-theme accent and `color.lagoon` the light-theme accent. On light backgrounds the pin is mint with a lagoon outline, so it stays distinct from the lagoon nodes.
- `brand.wordmark` is the logo text. The product name in prose, titles, the manifest, and alt text remains `brand.displayName` (GrooveMap).

## Reproduction

```sh
just brand-render
just brand
```

The renderer uses only pinned Node.js standard-library APIs. Text is never live SVG text: [`font.mjs`](font.mjs) reads the vendored variable font (cmap, glyf, gvar with IUP, and GPOS pair kerning), sets each string at its `type.weight`, and writes it as path data. The assets therefore render identically on GitHub, in link previews, and offline, and embed no font software. `scripts/brand-font.test.mjs` pins the reader's layout to HarfBuzz reference values. Given the same tracked inputs it produces byte-identical source assets. Consumers that require PNG or ICO outputs should add an explicitly pinned rasterizer and retain the SVG originals as provenance.

`assets.sha256` fixes the reviewed 12-file output set. `just brand` first renders in check mode and then verifies every output byte against that manifest.

## Strata state tokens

`tokens.json` also holds the color tokens of the Strata graph view ([ADR 0016](../docs/adr/0016-strata-graph-view.md), section 4). Color there is a state, so no state may be mistaken for the color of an entity type.

- `entity` holds the entity-type colors of today's Explore palette (artist green, category blue, genre yellow, label slate, release pink). They are recorded here so that collisions can be checked, and they are the same in both themes.
- `state` holds one object per vocabulary, and each token has a `light` and a `dark` value:
  - `collector` (concept A): `none`, `wanted`, `owned`, `wantedOwned`.
  - `lifecycle` (concept B): `absent`, `emerging`, `established`, `reviving`, `declining`, and `provisional`. `provisional` is the color of the treatment for the latest two years, whose counts are still growing. A renderer draws it as a dashed outline or hatch over the stage fill, so the cue is never color alone.
  - `fit` (concept C′): `affinity`, `novelty`, `bridge`, `redundancy`. These are the Fit components that can be drawn on the atlas.
  - `identity` (concept D): `notRecorded`, `discogsOnly`, `musicbrainzOnly`, `unresolved`, `split`, `linked`, `superseded`.

`just brand` proves, through [`scripts/brand-tokens.mjs`](../scripts/brand-tokens.mjs), that in each theme:

- every state has WCAG 2 contrast of at least 4.5:1 on each background it is drawn on: `void` and `deep` in the dark theme, and `lightBackground` in the light theme. A white card is lighter than `lightBackground`, so it passes too;
- every state is at least 15 CIEDE2000 from every entity-type color and from the brand mint and lagoon accents;
- states drawn in one view are at least 15 CIEDE2000 apart. C′ is drawn on B's atlas, so the `fit` and `lifecycle` states form one view.

The rendered `tokens.css` names them `--groovemap-entity-<type>` and `--groovemap-state-<vocabulary>-<state>-<light|dark>`. A consumer picks the value for its own theme mechanism. Neutral states (`none`, `absent`, `notRecorded`) are warm grays, so they stay apart from the slate label color.

## Promotion provenance

Public consumer source records in the organization profile, the Pages site, Graph Explorer,
and Operations Console pin Design commit `59c9fd3c8bbdfa676e0b7bb3d463fc766c1f3c0d` and its
asset digests. The Degrees rebrand changes all 12 outputs and renames the accent tokens:
`--groovemap-cyan`, `--groovemap-cyan-glow`, `--groovemap-purple`, and
`--groovemap-purple-light` are replaced by `--groovemap-mint` and `--groovemap-lagoon`, and
`--groovemap-light-muted-text` is new. Consumers keep the earlier bytes until each is
re-promoted. Those records prove which reviewed Design bytes were promoted; they do not
authorize this repository to modify a consumer.

Private promotion systems pin reviewed Design revisions independently and keep their
operational configuration outside this public repository. A future source change must
regenerate the 12 outputs, update `assets.sha256`, pass `just brand`, and be promoted through
each consumer's own review boundary.

## Font licensing

[`fonts/Jura[wght].ttf`](fonts/) is Jura by Daniel Johnson and Cyreal (upstream `ossobuffo/jura`), copied unmodified from `google/fonts` `ofl/jura` at commit `6e4b84c976cadb3c49a40fd9a1c203e4f7fcf2da`. It is licensed under the SIL Open Font License 1.1, whose text is in [`fonts/OFL.txt`](fonts/OFL.txt); the font is not covered by the repository's MIT License. `just brand` verifies both files against their recorded SHA-256 digests.

The rendered assets contain glyph outlines, not font software. Applications that set UI text in Jura load it themselves, for example from Google Fonts, under the same license.

The source monorepo also contained Space Grotesk TTF files without an adjacent OFL or other font notice. Those binaries are intentionally **not** promoted here.
