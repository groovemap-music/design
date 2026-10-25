// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { loadFont, outlineText } from "../brand/font.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const font = loadFont(resolve(root, "brand/fonts/Jura[wght].ttf"));

// Reference values were taken from HarfBuzz (uharfbuzz 0.45.0) shaping Jura at wght=500 with kerning on.
test("the wordmark lays out with HarfBuzz's glyphs, advances, and kerning", () => {
  const layout = font.layout("groovemap", { wght: 500 }).map(({ glyph, x, advance }) => [glyph, x, advance]);
  assert.deepEqual(layout, [
    [275, 0, 1241], [356, 1241, 787], [321, 1988, 1226], [321, 3214, 1226], [397, 4400, 1018],
    [252, 5378, 1226], [312, 6604, 1763], [210, 8327, 1231], [352, 9558, 1260],
  ]);
});

test("pair kerning comes from the GPOS kern feature", () => {
  assert.equal(font.kern(font.glyphId("r"), font.glyphId("o")), -40);
  assert.equal(font.kern(font.glyphId("p"), font.glyphId(".")), -100);
  assert.equal(font.kern(font.glyphId("o"), font.glyphId("o")), 0);
});

test("the weight axis normalizes from the default and varies advances through gvar", () => {
  assert.deepEqual(font.axes, [{ tag: "wght", min: 300, default: 300, max: 700 }]);
  assert.deepEqual(font.normalize({ wght: 500 }), [0.5]);
  assert.deepEqual(font.normalize({ wght: 900 }), [1]);
  const g = font.glyphId("g");
  assert.equal(font.instance(g, font.normalize({ wght: 300 })).advance, 1186);
  assert.equal(font.instance(g, font.normalize({ wght: 700 })).advance, 1296);
});

test("outlined text is deterministic path data with a measured width", () => {
  const first = outlineText(font, [{ text: "groovemap", weight: 500, size: 140 }]);
  const second = outlineText(font, [{ text: "groovemap", weight: 500, size: 140 }]);
  assert.equal(first.d, second.d);
  assert.match(first.d, /^M[-\d. ]+[LQ]/);
  assert.equal(first.width, Math.round(((9558 + 1260) * 140) / 2000 * 100) / 100);
});

test("a character the font lacks is rejected instead of silently dropped", () => {
  assert.throws(() => font.layout("groove\u{1F3B5}", { wght: 500 }), /no glyph/);
});
