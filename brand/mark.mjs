// SPDX-License-Identifier: MIT

// The "Label web" mark, drawn in a 100-unit box. A record with a brass label; a two-level
// graph is printed on the label, branching out from the spindle hole, which is cut as a map
// pin so the hole is the graph's hub. The small variant (favicons) drops the grooves and keeps
// three bold nodes on a larger label so the graph still reads at 16 px.

const GROOVES = [43.5, 40.5, 37.5, 34.5];
const LEVEL_ONE = [-2.3, -0.85, 0.6, 2.1];
const LEVEL_TWO = [[-2.65, 0], [-1.95, 0], [-0.5, 2], [1.2, 2], [2.45, 3]];
const SMALL_NODES = [-2.25, -0.55, 1.55];

const fmt = (n) => { const s = (Math.round(n * 100) / 100).toString(); return s === "-0" ? "0" : s; };
const polar = (r, a) => [50 + r * Math.cos(a), 50 + r * Math.sin(a)];
const line = ([x1, y1], [x2, y2]) => `<line x1="${fmt(x1)}" y1="${fmt(y1)}" x2="${fmt(x2)}" y2="${fmt(y2)}"/>`;
const node = ([x, y], r, fill) => `<circle cx="${fmt(x)}" cy="${fmt(y)}" r="${r}" fill="${fill}"/>`;

// The spindle hole as a map pin whose head is centered on the label; h is the head radius.
function pinHole(h) {
  const x = 50, y = 50 + h * 1.15;
  return `M${fmt(x)} ${fmt(y)}C${fmt(x - h * 0.35)} ${fmt(y - h * 0.5)} ${fmt(x - h)} ${fmt(y - h * 1.05)} ${fmt(x - h)} ${fmt(y - h * 1.75)}`
    + `A${h} ${h} 0 1 1 ${fmt(x + h)} ${fmt(y - h * 1.75)}C${fmt(x + h)} ${fmt(y - h * 1.05)} ${fmt(x + h * 0.35)} ${fmt(y - h * 0.5)} ${fmt(x)} ${fmt(y)}Z`;
}

// colors: { background, disc, edge, groove, label, print }
export function markBody(colors, { small = false } = {}) {
  const disc = `<circle cx="50" cy="50" r="46" fill="${colors.disc}" stroke="${colors.edge}" stroke-width="1.2"/>`;
  if (small) {
    const nodes = SMALL_NODES.map((a) => polar(21, a));
    return disc
      + `<circle cx="50" cy="50" r="33" fill="${colors.label}"/>`
      + `<g stroke="${colors.print}" stroke-width="4" stroke-linecap="round">${nodes.map((p) => line([50, 50], p)).join("")}</g>`
      + nodes.map((p) => node(p, 6, colors.print)).join("")
      + `<path d="${pinHole(8)}" fill="${colors.background}"/>`;
  }
  const one = LEVEL_ONE.map((a) => polar(13.5, a));
  const two = LEVEL_TWO.map(([a, parent]) => [polar(22, a), parent]);
  const edges = [...one.map((p) => line([50, 50], p)), ...two.map(([p, parent]) => line(one[parent], p)), line(one[0], one[1])];
  return disc
    + `<g fill="none" stroke="${colors.groove}" stroke-width=".7" opacity=".22">${GROOVES.map((r) => `<circle cx="50" cy="50" r="${r}"/>`).join("")}</g>`
    + `<path d="M21 30A35 35 0 0 1 39 16" fill="none" stroke="${colors.groove}" stroke-width="2" stroke-linecap="round" opacity=".28"/>`
    + `<circle cx="50" cy="50" r="28" fill="${colors.label}"/>`
    + `<g stroke="${colors.print}" stroke-width="1.7" stroke-linecap="round">${edges.join("")}</g>`
    + one.map((p) => node(p, 3.2, colors.print)).join("")
    + two.map(([p]) => node(p, 2.6, colors.print)).join("")
    + `<path d="${pinHole(5)}" fill="${colors.background}"/>`;
}
