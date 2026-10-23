// SPDX-License-Identifier: MIT
// The mockup's greedy label placement (Strata.layoutLabels), lifted out so every renderer uses the
// same rule: sort by priority, drop any label that would overlap one already placed, except
// priority 0 (hovered or selected), which always shows.

export function placeLabels(items, placed, w, h) {
  items.sort((a, b) => a.p - b.p);
  const shown = [];
  for (const it of items) {
    const hit = it.x < -20 || it.x + it.w > w + 20 || it.y < -10 || it.y > h || placed.some((q) => it.x < q.x + q.w && it.x + it.w > q.x && it.y < q.y + q.h && it.y + it.h > q.y);
    if (hit && it.p > 0) { it.shown = false; continue; }
    placed.push(it);
    it.shown = true;
    shown.push(it);
  }
  return shown;
}

// Overlap census over measured boxes: how many boxes touch no other box.
export function overlapCensus(boxes) {
  const n = boxes.length;
  const bad = new Uint8Array(n);
  let pairs = 0;
  const order = boxes.map((b, i) => i).sort((a, b) => boxes[a].x - boxes[b].x);
  for (let i = 0; i < n; i++) {
    const a = boxes[order[i]];
    for (let j = i + 1; j < n; j++) {
      const b = boxes[order[j]];
      if (b.x >= a.x + a.w - 0.5) break;
      if (a.y < b.y + b.h - 0.5 && a.y + a.h > b.y + 0.5 && a.x < b.x + b.w - 0.5) { pairs++; bad[order[i]] = 1; bad[order[j]] = 1; }
    }
  }
  return { boxes: n, pairs, clean: n - bad.reduce((s, x) => s + x, 0) };
}
