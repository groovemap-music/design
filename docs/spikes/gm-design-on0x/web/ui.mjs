// SPDX-License-Identifier: MIT
// Renderer-independent chrome: panel, readouts, plane buttons, keyboard, and the table that is the
// non-visual equivalent. Ported from the mockup's buildDom/renderPanel/renderOutline, with CSSOM in
// place of inline style attributes so it runs under a style-src 'self' policy.

import { STATES, LEGEND, PLANES, EDGE_KINDS } from '../lib/model.mjs';

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const tok = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888888';
const fmtMonth = (v) => { const y = Math.floor(v + 1e-6); const m = Math.min(11, Math.floor((v - y) * 12 + 1e-6)); return ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m] + ' ' + y; };

function paintChips(root) {
  for (const el of root.querySelectorAll('[data-c]')) el.style.setProperty('--c', el.dataset.c.startsWith('--') ? `var(${el.dataset.c})` : el.dataset.c);
}

export class Chrome {
  constructor(app) {
    this.app = app;
    this.panel = document.querySelector('.panel');
    this.readouts = document.querySelector('.readouts');
    this.stage = document.querySelector('.stage');
    this.outline = document.querySelector('.outline');
    this.outlineBody = document.querySelector('.outline-body');
    const seg = document.querySelector('.seg');
    seg.innerHTML = ['<button type="button" aria-pressed="true" data-solo="">All planes</button>'].concat(PLANES.map((p, i) => `<button type="button" aria-pressed="false" data-solo="${i}">L${i} ${esc(p)}</button>`)).join('');
    seg.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      seg.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      app.setSolo(b.dataset.solo === '' ? null : +b.dataset.solo);
    }));
    document.querySelectorAll('.stage-ctl button').forEach((b) => b.addEventListener('click', () => app.zoom(b.dataset.z)));
    this.panel.addEventListener('click', (e) => {
      const t = e.target.closest('button[data-tr]'); if (t && !t.disabled) app.transition(+t.dataset.tr);
      const s = e.target.closest('button[data-sel]'); if (s) app.select(app.view.byId.get(s.dataset.sel));
      const x = e.target.closest('button[data-expand]'); if (x) app.expand(app.view.byId.get(x.dataset.expand));
    });
    this.outline.addEventListener('toggle', () => { if (this.outline.open) this.renderTable(); });
    this.stage.setAttribute('aria-label', 'Discography strata: credits, masters, and releases on three planes. Arrow keys orbit, plus and minus zoom, PageUp and PageDown move to the parent or first child, [ and ] move to the previous or next node on the same plane, Enter expands a count node, Escape clears the selection.');
    this.stage.addEventListener('keydown', (e) => this.key(e));
    const valid = document.getElementById('valid'), tx = document.getElementById('tx');
    valid.addEventListener('change', () => { document.getElementById('valid-o').textContent = valid.value; app.setValid(+valid.value); });
    tx.addEventListener('input', () => { document.getElementById('tx-o').textContent = fmtMonth(+tx.value); app.setTx(+tx.value); });
  }

  key(e) {
    const app = this.app, v = app.view, s = app.selected;
    if (e.target !== this.stage) return;
    let used = true;
    const plane = (l) => v.nodes.filter((n) => n.level === l).sort((a, b) => a.z - b.z || a.x - b.x);
    switch (e.key) {
      case 'ArrowLeft': app.orbit(0.12); break;
      case 'ArrowRight': app.orbit(-0.12); break;
      case 'ArrowUp': app.tilt(0.08); break;
      case 'ArrowDown': app.tilt(-0.08); break;
      case '+': case '=': app.zoom('in'); break;
      case '-': app.zoom('out'); break;
      case 'PageUp': app.select(s && s.parent ? v.byId.get(s.parent) : plane(0)[0]); break;
      case 'PageDown': { const k = s ? s.children[0] : plane(0)[0]; if (k) app.select(k); break; }
      case '[': case ']': {
        const list = plane(s ? s.level : 0);
        const i = s ? list.indexOf(s) : -1;
        app.select(list[(i + (e.key === ']' ? 1 : list.length - 1)) % list.length] || list[0]);
        break;
      }
      case 'Enter': if (s && s.agg) app.expand(s); else used = false; break;
      case 'Escape': app.select(null); break;
      default: used = false;
    }
    if (used) e.preventDefault();
  }

  readout(inv) {
    this.readouts.innerHTML = `<span>Nodes <b>${inv.perPlane.join(' / ')}</b></span><span>Hulls <b>${inv.hulls}</b> · in a foreign hull <b>${inv.intrusions}</b></span><span>Lateral edges <b>${inv.edges}</b> · crossings <b>${inv.crossings}</b></span>`;
  }

  renderPanel() {
    const app = this.app, v = app.view, m = app.model, n = app.selected;
    if (!n) {
      this.panel.innerHTML = `<span class="p-plane">Nothing selected</span><p class="p-explain">Select a pressing on the bottom plane to see which collector transitions its edges allow. Red-ringed pressings exist only in MusicBrainz.</p><span class="p-sec">States</span><div class="legend">${LEGEND.map((s) => `<span class="chip" data-c="${STATES[s].tok}"><i></i>${esc(STATES[s].label)}</span>`).join('')}</div>`;
      paintChips(this.panel);
      return;
    }
    const s = v.state(n);
    let body = '';
    if (n.agg) {
      body = `<p class="p-explain">${n.count} ${n.level === 2 ? 'pressings' : n.level === 1 ? 'masters' : 'credits'} folded to keep this plane under its node budget. ${esc(n.sub || '')}.</p><div class="tr"><button type="button" data-expand="${esc(n.id)}">Expand<span>Enter</span></button></div>`;
    } else if (n.level === 2) {
      const r = n.ref;
      const trs = m.transitionsFor(r);
      const past = m.T < m.txMax - 1e-6;
      body = `<span class="p-sec">Transitions</span><div class="tr-list">` + trs.map((t) => {
        const g = m.guardFor(r, t);
        const blocked = past || (g && g.block);
        const why = past ? 'History is read-only. Move "Recorded as of" to today to record a change.' : g && g.block ? g.block : g && g.warn ? g.warn : '';
        const dest = (g && g.redirect) || t.to;
        return `<div class="tr"><button type="button" data-tr="${t.i}" ${blocked ? 'disabled' : ''}>${esc(t.label)}<span>→ ${esc(STATES[dest].label)}</span></button>${why ? `<p class="why${!blocked ? ' warn' : ''}">${esc(why)}</p>` : ''}</div>`;
      }).join('') + '</div>';
      if (r.hist.length) body += `<span class="p-sec">Recorded history</span><ul class="hist">${r.hist.map((h) => `<li>${fmtMonth(h[0])} → ${esc(STATES[h[1]].label)}</li>`).join('')}</ul>`;
    } else if (n.level === 1) {
      const ps = n.ref.children;
      const missing = ps.filter((k) => m.recorded(k) !== 'owned');
      body = `<p class="p-explain">${n.ref.lane ? `This credit's ${ps.length} release${ps.length > 1 ? 's' : ''} with no master on Discogs.` : `Derived from its ${ps.length} pressing${ps.length > 1 ? 's' : ''}: owned when any pressing is owned.`} ${missing.length} not owned.</p><span class="p-sec">Pressings</span><ul class="edges-l">${ps.map((k) => `<li>${esc(k.label)} · ${esc(STATES[m.recorded(k)].label)}${k.prov === 'mb' ? ' · MusicBrainz only' : ''}</li>`).join('')}</ul>`;
    } else {
      const ms = n.ref.children; const own = ms.filter((x) => m.state(x) === 'owned').length;
      body = `<p class="p-explain">${own} of ${ms.length} masters owned.</p>`;
    }
    const es = n.ref ? m.lateral(n.ref) : [];
    const edgeHtml = es.length ? `<span class="p-sec">Lateral edges</span><ul class="edges-l">${es.slice(0, 12).map((e) => `<li>${esc(EDGE_KINDS[e.kind].label)} → ${esc((e.na === n.ref ? e.nb : e.na).label)}</li>`).join('')}${es.length > 12 ? `<li>${es.length - 12} more in the table</li>` : ''}</ul>` : '';
    const parent = n.parent ? v.byId.get(n.parent) : null;
    const nav = `<div class="legend">${parent ? `<button type="button" class="chip" data-sel="${esc(parent.id)}">↑ ${esc(parent.label)}</button>` : ''}${n.children.slice(0, 4).map((k) => `<button type="button" class="chip" data-sel="${esc(k.id)}">↓ ${esc(k.label)}</button>`).join('')}</div>`;
    this.panel.innerHTML = `<span class="p-plane">L${n.level} · ${esc(PLANES[n.level])}${n.ref && !m.known(n.ref) ? ' · not yet in catalog' : ''}</span><h4>${esc(n.label)}</h4><span class="chip" data-c="${STATES[s].tok}"><i></i>${esc(STATES[s].label)}</span>${app.flash ? `<p class="p-explain">${esc(app.flash)}</p>` : ''}${body}${edgeHtml}${nav}`;
    paintChips(this.panel);
  }

  // Every node of the model, folded or not, with its path, state, and blocked reason.
  renderTable() {
    const m = this.app.model;
    const t0 = performance.now();
    const rows = [];
    const path = (n) => { const p = []; let x = n; while (x.parent) { x = m.byId.get(x.parent); p.unshift(x.label); } return p.join(' › '); };
    for (const n of m.nodes) {
      if (!m.vis.has(n)) continue;
      rows.push(`<tr><td>L${n.level} ${esc(PLANES[n.level])}</td><td>${esc(n.label)}</td><td>${esc(path(n))}</td><td>${n.year ?? ''}</td><td>${esc(STATES[m.state(n)].label)}</td><td>${esc(m.blockedReason(n) || '')}</td></tr>`);
    }
    this.outlineBody.innerHTML = `<table><caption>${rows.length} rows</caption><thead><tr><th scope="col">Plane</th><th scope="col">Name</th><th scope="col">Under</th><th scope="col">Year</th><th scope="col">State</th><th scope="col">Cannot change because</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
    this.tableMs = performance.now() - t0;
  }
}
