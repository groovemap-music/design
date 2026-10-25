// SPDX-License-Identifier: MIT

// The "Degrees" mark, drawn in a 100-unit box. A seed sits at the center; each contour ring is
// one more degree of separation, and edges run outward ring by ring. The inner ring is a true
// circle and the outer rings drift into terrain contours. A pin on the outer ring marks the
// viewer's position. The small variant (favicons) keeps two rings and three nodes.

const RADII = [15, 27, 39];
const DRIFT = [0, 0.06, 0.12];
const NODE_ANGLES = [[-1.9, 0.2, 2.4], [-1.3, 0.75, 2.9], [-0.75, 1.5, 3.78]];
const SMALL_ANGLES = [[], [], [-0.75, 1.5, 3.78]];
const RING_SAMPLES = 96;

const fmt = (n) => { const s = (Math.round(n * 100) / 100).toString(); return s === "-0" ? "0" : s; };
const wobble = (a) => 0.55 * Math.sin(2 * a + 0.6) + 0.35 * Math.cos(3 * a - 0.4) + 0.18 * Math.sin(5 * a + 1.1);

function onRing(ring, angle) {
  const r = RADII[ring] * (1 + DRIFT[ring] * wobble(angle));
  return [50 + r * Math.cos(angle), 50 + r * Math.sin(angle)];
}

function ringPath(ring) {
  const points = [];
  for (let k = 0; k < RING_SAMPLES; k++) points.push(onRing(ring, (k / RING_SAMPLES) * Math.PI * 2).map(fmt).join(" "));
  return `M${points.join("L")}Z`;
}

const line = ([x1, y1], [x2, y2]) => `<line x1="${fmt(x1)}" y1="${fmt(y1)}" x2="${fmt(x2)}" y2="${fmt(y2)}"/>`;
const node = ([x, y], r, fill, stroke, width) => `<circle cx="${fmt(x)}" cy="${fmt(y)}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${width}"/>`;

// colors: { background, accent, pinFill, pinStroke }
export function markBody(colors, { small = false } = {}) {
  const nodes = (small ? SMALL_ANGLES : NODE_ANGLES).map((angles, ring) => angles.map((a) => onRing(ring, a)));
  const rings = (small ? [1, 2] : [0, 1, 2]).map((ring) => `<path d="${ringPath(ring)}"/>`).join("");
  const edges = [];
  if (small) {
    for (const p of nodes[2]) edges.push(line([50, 50], p));
  } else {
    for (const p of nodes[0]) edges.push(line([50, 50], p));
    for (let j = 0; j < 3; j++) edges.push(line(nodes[0][j], nodes[1][j]), line(nodes[1][j], nodes[2][j]));
    edges.push(line(nodes[1][0], nodes[0][1]));
  }
  const dots = nodes.flatMap((ring, i) => ring.map((p, j) => {
    const pin = i === 2 && j === 0;
    const r = small ? (pin ? 9 : 7) : pin ? 5.5 : [3.8, 3.4, 3.4][i];
    const width = small ? 3 : 2;
    return pin ? node(p, r, colors.pinFill, colors.pinStroke, width) : node(p, r, colors.accent, colors.background, width);
  })).join("");
  return `<g fill="none" stroke="${colors.accent}" stroke-width="${small ? 3 : 1.3}" opacity=".45">${rings}</g>`
    + `<g stroke="${colors.accent}" stroke-width="${small ? 4.5 : 2}" stroke-linecap="round">${edges.join("")}</g>`
    + `<circle cx="50" cy="50" r="${small ? 9 : 6}" fill="${colors.accent}"/>`
    + `<circle cx="50" cy="50" r="${small ? 3 : 1.8}" fill="${colors.background}"/>${dots}`;
}
