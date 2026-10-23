// SPDX-License-Identifier: MIT
// Accessibility checks and the three collector tasks, per renderer, in headed Chromium.
//   node scripts/check_a11y_tasks.mjs --budget 3,12,16 --layout spaced > results/a11y_tasks.json
// Tasks are measured as reachability, not judged: whether each target is drawn, on screen, and
// clickable at the default view, and how many actions reach the answer. Whether a renderer makes the
// task easy is the maintainer's judgment and is recorded separately.

import { createRequire } from 'node:module';
import { join } from 'node:path';
import { serve, PREFIX } from './serve.mjs';

const { chromium } = createRequire(join(PREFIX, 'package.json'))('playwright');

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const BUDGET = arg('budget', '6,20,30');
const RENDERERS = arg('renderers', 'webgl,webgl-inst,iso,d3').split(',');
const SCALES = arg('scales', '50,500,5000,20000').split(',').map(Number);
const LAYOUT = arg('layout', 'mockup');
const server = await serve(0);
const base = `http://127.0.0.1:${server.address().port}/web/index.html`;
const browser = await chromium.launch({ headless: false });
const out = { budget: BUDGET, layout: LAYOUT, browser: `chromium ${browser.version()}`, runs: [] };

async function open(r, n, extra = {}, query = '') {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, ...extra });
  const page = await ctx.newPage();
  page.setDefaultTimeout(180000);
  await page.goto(`${base}?r=${r}&n=${n}&budget=${BUDGET}${LAYOUT === 'spaced' ? '&spaced=1' : ''}${query}`);
  await page.evaluate(() => window.__h.ready);
  if (r === 'd3') await page.evaluate(() => window.__h.app.renderer.settle(20000));
  await page.waitForTimeout(300);
  return { ctx, page };
}

for (const r of RENDERERS) for (const n of SCALES) {
  const run = { renderer: r, scale: n };
  let { ctx, page } = await open(r, n);
  // Keyboard: planes and nodes.
  await page.focus('.stage');
  const sel = () => page.evaluate(() => { const s = window.__h.app.selected; return s ? { id: s.id, level: s.level, parent: s.parent } : null; });
  // PageDown to a credit and to one of its masters, ] along the master plane until a master with
  // pressings on the plane, PageDown to a pressing, PageUp twice back to the credit, Escape.
  const steps = [];
  const press = async (key) => { await page.keyboard.press(key); const s = await sel(); steps.push({ key, sel: s }); return s; };
  // When every master is folded, Enter on a masters count node drills down a page first.
  await press('PageDown'); await press('PageDown');
  const cur = () => page.evaluate(() => { const s = window.__h.app.selected; return { kids: !!(s && s.children.length), agg: !!(s && s.agg) }; });
  let hops = 0, drilled = false;
  while (!(await cur()).kids && hops < 60) {
    if ((await cur()).agg && !drilled) { await press('Enter'); drilled = true; continue; }
    await press(']'); hops++;
  }
  const down = await press('PageDown'), up1 = await press('PageUp'), up2 = await press('PageUp'), esc = await press('Escape');
  const ok = steps[0].sel?.level === 0 && steps[1].sel?.level === 1 && down?.level === 2 && up1?.level === 1 && up2?.level === 0 && esc === null;
  run.keyboard = { ok, drilledWithEnter: drilled, siblingHops: hops, keys: steps.map((s) => s.key).join(' '), levels: steps.map((s) => (s.sel ? s.sel.level : '-')).join(' ') };
  run.keyboard.panelAriaLive = await page.evaluate(() => document.querySelector('.panel').getAttribute('aria-live'));
  run.keyboard.focusable = await page.evaluate(() => [...document.querySelectorAll('button, input, summary, [tabindex]')].map((e) => (e.getAttribute('aria-label') || e.textContent || e.id).trim().slice(0, 24)));
  // Non-visual equivalent: the table, against the model as oracle.
  await page.evaluate(() => { document.querySelector('.outline').open = true; });
  await page.waitForTimeout(200);
  run.table = await page.evaluate(() => {
    const app = window.__h.app, m = app.model;
    const rows = document.querySelectorAll('.outline tbody tr');
    let blockedRows = 0; for (const tr of rows) if (tr.lastElementChild.textContent) blockedRows++;
    const oracleRows = m.nodes.filter((x) => m.vis.has(x)).length;
    const oracleBlocked = m.nodes.filter((x) => m.vis.has(x) && m.blockedReason(x)).length;
    return { rows: rows.length, oracleRows, blockedRows, oracleBlocked, renderMs: +app.chrome.tableMs.toFixed(0), match: rows.length === oracleRows && blockedRows === oracleBlocked };
  });
  // Tasks.
  run.tasks = await page.evaluate(async () => {
    const app = window.__h.app, v = app.view, m = app.model, R = app.renderer;
    const canvasRect = document.querySelector('.stage').getBoundingClientRect();
    const clickable = (n) => { const p = R.screenPos(n); if (!p.ok || p.x < canvasRect.left || p.x > canvasRect.right || p.y < canvasRect.top || p.y > canvasRect.bottom) return false; return R.pick(p.x, p.y) === n; };
    const drawn = (x) => { const rep = v.rep.get(x); return rep && !rep.agg ? rep : null; };
    // Drill-down reach: open the count node holding x (and the next page, as needed) until x is
    // drawn, then check it is clickable. Restores the default view afterwards.
    // Each step plans the next view without drawing it; only the final view is rendered.
    const reach = (x) => {
      let state = { pinned: new Set(), focus: null, seen: new Set() }, view = v;
      for (let actions = 0; actions < 200; actions++) {
        const rep = view.rep.get(x);
        if (!rep) return { drawn: false, actions };
        if (!rep.agg) {
          if (!actions) return { drawn: true, clickable: clickableIn(rep), actions };
          app.pinned = state.pinned; app.focus = state.focus; app.selected = null; app.build();
          if (app.renderer.settle) app.renderer.settle(5000);
          return { drawn: true, clickable: clickableIn(app.view.byId.get(rep.id)), actions };
        }
        state = app.drill(state, rep);
        view = app.viewFor(state);
      }
      return { drawn: false, actions: 200 };
    };
    const clickableIn = (n) => { const R2 = app.renderer; const p = R2.screenPos(n); if (!p.ok || p.x < canvasRect.left || p.x > canvasRect.right || p.y < canvasRect.top || p.y > canvasRect.bottom) return false; return R2.pick(p.x, p.y) === n; };
    const reset = () => { app.seen = new Set(); if (!app.pinned.size && !app.focus) return; app.pinned = new Set(); app.focus = null; app.selected = null; app.build(); if (app.renderer.settle) app.renderer.settle(5000); };
    const reachAll = (xs) => {
      const rs = xs.map((x) => { const r = reach(x); reset(); return r; });
      const acts = rs.filter((r) => r.drawn).map((r) => r.actions).sort((a, b) => a - b);
      return { targets: xs.length, reached: rs.filter((r) => r.drawn).length, clickableAfter: rs.filter((r) => r.clickable).length, medianActions: acts.length ? acts[acts.length >> 1] : null, maxActions: acts.length ? acts[acts.length - 1] : null };
    };
    // T1: a missing pressing of an owned master.
    const owned = m.nodes.filter((x) => x.level === 1 && m.vis.has(x) && m.state(x) === 'owned' && x.children.some((k) => m.recorded(k) !== 'owned'));
    const t1Masters = owned.map((x) => drawn(x));
    const t1Missing = owned.flatMap((x) => x.children.filter((k) => m.vis.has(k) && m.recorded(k) !== 'owned'));
    const t1 = { ownedMastersWithGaps: owned.length, mastersDrawn: t1Masters.filter(Boolean).length, mastersClickable: t1Masters.filter((x) => x && clickable(x)).length, missingPressings: t1Missing.length, missingDrawn: t1Missing.filter((k) => drawn(k)).length, actions: 'select the master (1); its pressings and their states list in the panel; a folded master needs its count node opened first' };
    // T2: items that cannot change state, and why.
    const blocked = m.nodes.filter((x) => m.vis.has(x) && m.blockedReason(x));
    const t2 = { blocked: blocked.length, drawn: blocked.filter((k) => drawn(k)).length, clickable: blocked.filter((k) => drawn(k) && clickable(drawn(k))).length, ringed: r => null, actions: 'a red ring marks a drawn blocked pressing; selecting it shows the reason (1); the table lists every blocked item with its reason (1)' };
    delete t2.ringed;
    // T3: trace a release to its credit.
    const rels = v.nodes.filter((x) => x.level === 2 && !x.agg);
    let traced = 0, clickableRel = 0;
    for (const x of rels) {
      if (clickable(x)) clickableRel++;
      const cyl = v.cylinder(x); const master = v.byId.get(x.parent); const credit = master && v.byId.get(master.parent);
      if (master && credit && cyl.has(master) && cyl.has(credit)) traced++;
    }
    app.select(null);
    const t3 = { releasesDrawn: rels.length, clickable: clickableRel, cylinderReachesCredit: traced, actions: 'select the pressing (1): the highlight runs up through its master to its credit; PageUp twice walks it by keyboard' };
    // Drill-down reach for the targets the default view folds (capped at 12 per task).
    t1.drill = reachAll(owned.filter((x) => !drawn(x)).slice(0, 12));
    t1.drillMissing = reachAll(t1Missing.filter((x) => !drawn(x)).slice(0, 12));
    t2.drill = reachAll(blocked.filter((x) => !drawn(x)).slice(0, 12));
    const allRels = m.nodes.filter((x) => x.level === 2 && m.vis.has(x));
    t3.drill = reachAll(allRels.filter((x, i) => !drawn(x) && i % Math.max(1, Math.floor(allRels.length / 12)) === 0).slice(0, 12));
    return { t1, t2, t3 };
  });
  await ctx.close();
  // Reduced motion: camera reset after an orbit, counting animated frames.
  for (const reduced of ['no-preference', 'reduce']) {
    ({ ctx, page } = await open(r, n, { reducedMotion: reduced }));
    const frames = await page.evaluate(async () => {
      const app = window.__h.app; await app.orbitFor(300); app.renderer.tweenFrames = 0; app.zoom('reset');
      await new Promise((res) => setTimeout(res, 800));
      return { reduce: app.reduce, tweenFrames: app.renderer.tweenFrames ?? null, simAlpha: app.renderer.sim ? app.renderer.sim.alpha() : null };
    });
    (run.reducedMotion ||= {})[reduced] = frames;
    await ctx.close();
  }
  out.runs.push(run);
  process.stderr.write(`${r} ${n} keyboard=${run.keyboard.ok} table=${run.table.match} t1=${JSON.stringify(run.tasks.t1).slice(0, 120)}\n`);
}
await browser.close(); server.close();
console.log(JSON.stringify(out, null, 1));
