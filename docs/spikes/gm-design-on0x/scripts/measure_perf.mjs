// SPDX-License-Identifier: MIT
// Frame-rate and legibility matrix through Playwright: browser x renderer x scale x (raw | budget)
// x (desktop | phone). Browsers run headed: headless Chromium falls back to SwiftShader and caps
// animation frames, which would measure the harness rather than the renderer.
//   node scripts/measure_perf.mjs --budget 6,20,30 [--browsers chromium,firefox,webkit]
//     [--renderers webgl,webgl-inst,iso,d3] [--scales 50,500,5000,20000] [--orbit-ms 4000] > results/perf.json

import { createRequire } from 'node:module';
import { join } from 'node:path';
import { cpus, loadavg, totalmem } from 'node:os';
import { serve, PREFIX } from './serve.mjs';

const { chromium, firefox, webkit } = createRequire(join(PREFIX, 'package.json'))('playwright');

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const BROWSERS = arg('browsers', 'chromium,firefox,webkit').split(',');
const RENDERERS = arg('renderers', 'webgl,webgl-inst,iso,d3').split(',');
const SCALES = arg('scales', '50,500,5000,20000').split(',').map(Number);
const BUDGET = arg('budget', '');
const LAYOUT = arg('layout', 'mockup');
const ORBIT_MS = +arg('orbit-ms', 4000);
const TIMEOUT = +arg('timeout-ms', 180000);
const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 },
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
};
const TYPES = { chromium, firefox, webkit };

const stats = (deltas) => {
  const d = deltas.slice().sort((a, b) => a - b);
  if (!d.length) return { frames: 0 };
  const q = (p) => d[Math.min(d.length - 1, Math.floor(p * d.length))];
  return { frames: d.length, medianFps: +(1000 / q(0.5)).toFixed(1), p5Fps: +(1000 / q(0.95)).toFixed(1), worstFrameMs: +d[d.length - 1].toFixed(1) };
};
const median = (xs) => { const d = xs.slice().sort((a, b) => a - b); return d.length ? +d[d.length >> 1].toFixed(2) : null; };

const server = await serve(0);
const base = `http://127.0.0.1:${server.address().port}/web/index.html`;
const out = { orbitMs: ORBIT_MS, budget: BUDGET, layout: LAYOUT, host: { cpu: cpus()[0].model, cores: cpus().length, memGiB: Math.round(totalmem() / 2 ** 30), loadAvgStart: loadavg().map((x) => +x.toFixed(1)) }, browsers: {}, runs: [] };
for (const bn of BROWSERS) {
  const browser = await TYPES[bn].launch({ headless: false });
  {
    const p = await browser.newPage();
    await p.setContent('<canvas id=c></canvas>');
    out.browsers[bn] = {
      version: browser.version(),
      gl: await p.evaluate(() => { const gl = document.getElementById('c').getContext('webgl2'); const x = gl && gl.getExtension('WEBGL_debug_renderer_info'); return gl ? (x ? gl.getParameter(x.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)) : 'no webgl2'; }),
      cpuThrottle: bn === 'chromium' ? '4x via CDP Emulation.setCPUThrottlingRate' : 'not available in Playwright for this engine',
    };
    await p.close();
  }
  for (const [vp, vopts] of Object.entries(VIEWPORTS)) {
    const o = { ...vopts };
    if (bn === 'firefox') delete o.isMobile;
    for (const r of RENDERERS) for (const n of SCALES) for (const budget of ['', BUDGET].filter((b, i) => i === 0 || b)) {
      const run = { browser: bn, viewport: vp, renderer: r, scale: n, budget: budget || null, throttle: vp === 'phone' && bn === 'chromium' ? 4 : 1 };
      const ctx = await browser.newContext(o);
      const page = await ctx.newPage();
      try {
        if (run.throttle > 1) { const cdp = await ctx.newCDPSession(page); await cdp.send('Emulation.setCPUThrottlingRate', { rate: run.throttle }); }
        page.setDefaultTimeout(TIMEOUT);
        await page.goto(`${base}?r=${r}&n=${n}${budget ? `&budget=${budget}` : ''}${LAYOUT === 'spaced' ? '&spaced=1' : ''}`);
        const m = await page.evaluate(() => window.__h.ready);
        Object.assign(run, { ttffMs: +m.ttffMs.toFixed(0), buildMs: +m.buildMs.toFixed(0), generateMs: +m.generateMs.toFixed(0), fixtureNodes: m.fixtureNodes });
        const orbit = await page.evaluate((ms) => window.__h.app.orbitFor(ms), ORBIT_MS);
        Object.assign(run, stats(orbit.deltas), { medianWorkMs: median(orbit.work) });
        if (r === 'd3') run.settle = await page.evaluate(() => window.__h.app.renderer.settle(20000));
        else await page.evaluate(() => { window.__h.app.renderer.zoom('reset'); });
        await page.waitForTimeout(800);
        const c = await page.evaluate(() => window.__h.app.census());
        Object.assign(run, { perPlane: c.perPlane, onScreen: c.onScreen, labelsRendered: c.labelsRendered, labelsShown: c.labelsShown, overlapPairs: c.overlapPairs, cleanLabels: c.cleanLabels, labelShare: c.onScreen ? +(c.cleanLabels / c.onScreen).toFixed(3) : null, intrusions: c.inv.intrusions, crossings: c.inv.crossings, d3Crossings: c.d3Crossings ?? null });
        run.errors = await page.evaluate(() => window.__h.app.errors);
        run.csp = await page.evaluate(() => window.__h.app.csp);
      } catch (e) {
        run.error = String(e.message || e).split('\n')[0].slice(0, 200);
      }
      out.runs.push(run);
      run.loadAvg1 = +loadavg()[0].toFixed(1);
      process.stderr.write(`${bn} ${vp} ${r} ${n} ${budget || 'raw'} ttff=${run.ttffMs} fps=${run.medianFps}/${run.p5Fps} labels=${run.labelShare} ${run.error || ''}\n`);
      await ctx.close();
    }
  }
  await browser.close();
}
server.close();
out.host.loadAvgEnd = loadavg().map((x) => +x.toFixed(1));
console.log(JSON.stringify(out, null, 1));
