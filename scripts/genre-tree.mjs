// SPDX-License-Identifier: MIT

export const MAX_CHILDREN = 255;

// Structural checks the schema cannot express: sorted, unique, internally consistent counts and the
// share rule (ADR 0020): every pair has share >= 0.20, or is the sole (dominant) parent of its style.
export function validateGenreTree(tree) {
  const errors = [];
  const genres = tree.genres ?? [];
  const names = genres.map((entry) => entry.genre);
  if (JSON.stringify(names) !== JSON.stringify([...names].sort())) errors.push("genres must be sorted by name");
  if (new Set(names).size !== names.length) errors.push("genre names must be unique");
  for (const dropped of tree.rule?.dropped_genres ?? []) {
    if (names.includes(dropped)) errors.push(`dropped junk genre is present: ${dropped}`);
  }
  const perStyle = new Map();
  let pairs = 0;
  let maxChildren = 0;
  for (const entry of genres) {
    const children = entry.children ?? [];
    if (children.length > MAX_CHILDREN) errors.push(`${entry.genre} has ${children.length} children, over the ${MAX_CHILDREN}-option Choice limit`);
    maxChildren = Math.max(maxChildren, children.length);
    const styles = children.map((child) => child.style);
    if (new Set(styles).size !== styles.length) errors.push(`${entry.genre} repeats a style`);
    const order = children.map((child) => [child.records, child.style]);
    const expected = [...order].sort((a, b) => b[0] - a[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
    if (JSON.stringify(order) !== JSON.stringify(expected)) errors.push(`${entry.genre} children must be sorted by records descending, then name`);
    for (const child of children) {
      pairs += 1;
      if (child.genre_records > child.records) errors.push(`${entry.genre}/${child.style} genre_records exceeds the style's records`);
      if (child.genre_records > entry.records) errors.push(`${entry.genre}/${child.style} genre_records exceeds the genre's records`);
      const list = perStyle.get(child.style) ?? [];
      list.push({ genre: entry.genre, ...child });
      perStyle.set(child.style, list);
    }
  }
  let multi = 0;
  for (const [style, list] of perStyle) {
    if (list.length > 1) multi += 1;
    if (new Set(list.map((item) => item.records)).size > 1) errors.push(`style ${style} carries inconsistent record totals`);
    for (const item of list) {
      if (item.genre_records * 5 < item.records && list.length > 1) errors.push(`${item.genre}/${style} is below the 0.20 share and is not the dominant parent`);
    }
  }
  const counts = tree.counts ?? {};
  if (counts.genres !== genres.length) errors.push(`counts.genres is ${counts.genres}, expected ${genres.length}`);
  if (counts.styles !== perStyle.size) errors.push(`counts.styles is ${counts.styles}, expected ${perStyle.size}`);
  if (counts.pairs !== pairs) errors.push(`counts.pairs is ${counts.pairs}, expected ${pairs}`);
  if (counts.styles_with_2plus_parents !== multi) errors.push(`counts.styles_with_2plus_parents is ${counts.styles_with_2plus_parents}, expected ${multi}`);
  if (counts.max_children !== maxChildren) errors.push(`counts.max_children is ${counts.max_children}, expected ${maxChildren}`);
  const kinds = (tree.source?.inputs ?? []).map((input) => input.kind).sort();
  if (JSON.stringify(kinds) !== JSON.stringify(["masters", "releases"])) errors.push("source.inputs must be one masters and one releases file");
  for (const input of tree.source?.inputs ?? []) {
    if (!input.file?.includes(`_${tree.source.dump_date}_`)) errors.push(`${input.file} is not from dump ${tree.source.dump_date}`);
  }
  return errors;
}
