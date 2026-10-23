// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  BACKGROUNDS,
  MIN_CONTRAST,
  MIN_ENTITY_DELTA_E,
  STATE_VOCABULARIES,
  THEMES,
  contrastRatio,
  deltaE2000,
  deltaE2000Lab,
  validateStateTokens,
} from "./brand-tokens.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tokens = JSON.parse(readFileSync(resolve(root, "brand/tokens.json"), "utf8"));
const clone = () => structuredClone(tokens);

test("contrast ratio follows the WCAG 2 definition", () => {
  assert.equal(contrastRatio("#ffffff", "#000000"), 21);
  assert.equal(contrastRatio("#000000", "#000000"), 1);
  assert.equal(contrastRatio("#767676", "#ffffff").toFixed(2), "4.54");
  assert.equal(contrastRatio("#777777", "#ffffff").toFixed(2), "4.48");
});

test("CIEDE2000 reproduces the published reference pairs", () => {
  const reference = [
    [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425],
    [[50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615],
    [[50, 2.5, 0], [50, 0, -2.5], 4.3065],
    [[50, 2.5, 0], [73, 25, -18], 27.1492],
    [[60.2574, -34.0099, 36.2677], [60.4626, -34.1751, 39.4387], 1.2644],
    [[2.0776, 0.0795, -1.135], [0.9033, -0.0636, -0.5514], 0.9082],
  ];
  for (const [first, second, expected] of reference) assert.equal(deltaE2000Lab(first, second).toFixed(4), expected.toFixed(4));
  assert.equal(deltaE2000("#336699", "#336699"), 0);
  assert.equal(Math.round(deltaE2000("#ffffff", "#000000")), 100);
});

test("state tokens hold exactly the ADR 0016 vocabularies with a light and a dark value", () => {
  assert.deepEqual(Object.fromEntries(Object.entries(tokens.state).map(([name, states]) => [name, Object.keys(states)])), STATE_VOCABULARIES);
  for (const states of Object.values(tokens.state)) {
    for (const token of Object.values(states)) assert.deepEqual(Object.keys(token), THEMES);
  }
});

test("state tokens never collide with an entity-type color and meet AA contrast in both themes", () => {
  assert.deepEqual(validateStateTokens(tokens), []);
});

test("the entity-type colors mirror the Explore palette that the state tokens must avoid", () => {
  assert.deepEqual(tokens.entity, { artist: "#00e676", category: "#40c4ff", genre: "#ffd54f", label: "#78909c", release: "#ff5c8a" });
});

test("a state equal to an entity-type color is rejected in both themes", () => {
  const invalid = clone();
  invalid.state.collector.owned.dark = tokens.entity.artist;
  invalid.state.collector.owned.light = tokens.entity.release;
  const errors = validateStateTokens(invalid);
  assert.ok(errors.some((error) => error.startsWith("state.collector.owned.dark") && error.includes("artist")));
  assert.ok(errors.some((error) => error.startsWith("state.collector.owned.light") && error.includes("release")));
});

test("a state within the stated distance of an entity-type or brand accent color is rejected", () => {
  const invalid = clone();
  invalid.state.fit.novelty.dark = "#05e87a";
  invalid.state.fit.bridge.dark = "#00c0d8";
  const errors = validateStateTokens(invalid);
  const nearArtist = errors.find((error) => error.startsWith("state.fit.novelty.dark") && error.includes("artist"));
  assert.ok(nearArtist, errors.join("\n"));
  assert.match(nearArtist, new RegExp(`below ${MIN_ENTITY_DELTA_E}`));
  assert.ok(errors.some((error) => error.startsWith("state.fit.bridge.dark") && error.includes("brand.cyan")));
});

test("a state below AA contrast on its background is rejected in both themes", () => {
  const invalid = clone();
  invalid.state.identity.linked.dark = "#10301a";
  invalid.state.identity.linked.light = "#a8e0b4";
  const errors = validateStateTokens(invalid);
  for (const theme of THEMES) {
    const background = BACKGROUNDS[theme][0];
    assert.ok(errors.some((error) => error.startsWith(`state.identity.linked.${theme}`) && error.includes(`on ${background}`) && error.includes(`below ${MIN_CONTRAST}`)), errors.join("\n"));
  }
});

test("states drawn in the same view must stay distinguishable from each other", () => {
  const invalid = clone();
  invalid.state.lifecycle.declining.dark = tokens.state.fit.affinity.dark;
  const errors = validateStateTokens(invalid);
  assert.ok(errors.some((error) => error.startsWith("fit view:") && error.includes("state.fit.affinity.dark")), errors.join("\n"));
});

test("a missing, extra, or malformed state is rejected", () => {
  const missing = clone();
  delete missing.state.identity.superseded;
  assert.ok(validateStateTokens(missing).some((error) => error.includes("state.identity must hold exactly")));

  const extra = clone();
  extra.state.collector.shared = { light: "#112233", dark: "#aabbcc" };
  assert.ok(validateStateTokens(extra).some((error) => error.includes("state.collector must hold exactly")));

  const malformed = clone();
  malformed.state.fit.affinity.dark = "blue";
  assert.ok(validateStateTokens(malformed).some((error) => error.includes("state.fit.affinity.dark")));

  const oneTheme = clone();
  delete oneTheme.state.fit.affinity.light;
  assert.ok(validateStateTokens(oneTheme).some((error) => error.includes("state.fit.affinity must hold exactly")));
});

test("the rendered stylesheet carries every entity and state token for both themes", () => {
  const css = readFileSync(resolve(root, "brand/assets/tokens.css"), "utf8");
  assert.match(css, /--groovemap-entity-artist: #00e676;/);
  assert.match(css, new RegExp(`--groovemap-state-collector-wanted-owned-dark: ${tokens.state.collector.wantedOwned.dark};`));
  assert.match(css, new RegExp(`--groovemap-state-identity-musicbrainz-only-light: ${tokens.state.identity.musicbrainzOnly.light};`));
  const declared = css.match(/--groovemap-state-[a-z-]+: #[0-9a-f]{6};/g) ?? [];
  const expected = Object.values(STATE_VOCABULARIES).reduce((total, names) => total + names.length, 0) * THEMES.length;
  assert.equal(declared.length, expected);
});
