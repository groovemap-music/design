// SPDX-License-Identifier: MIT

// A minimal TrueType reader that outlines brand text from the vendored variable font, so SVG
// assets carry paths instead of live text and the toolchain stays at the Node.js standard
// library. It reads only what that needs: cmap, hmtx, glyf, gvar (with IUP), and GPOS pair
// kerning. Unsupported structures throw instead of rendering something subtly different.

import { readFileSync } from "node:fs";

const ON_CURVE = 0x01, X_SHORT = 0x02, Y_SHORT = 0x04, REPEAT = 0x08, X_SAME = 0x10, Y_SAME = 0x20;
const SHARED_POINTS = 0x8000, COUNT_MASK = 0x0fff;
const EMBEDDED_PEAK = 0x8000, INTERMEDIATE = 0x4000, PRIVATE_POINTS = 0x2000, INDEX_MASK = 0x0fff;
const DELTAS_ZERO = 0x80, DELTAS_WORDS = 0x40, DELTA_RUN_MASK = 0x3f, POINTS_WORDS = 0x80, POINT_RUN_MASK = 0x7f;

export function loadFont(path) {
  return new Font(readFileSync(path));
}

class Font {
  constructor(bytes) {
    this.data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    this.tables = {};
    const count = this.u16(4);
    for (let i = 0; i < count; i++) {
      const at = 12 + i * 16;
      const tag = String.fromCharCode(...[0, 1, 2, 3].map((k) => this.data.getUint8(at + k)));
      this.tables[tag] = this.u32(at + 8);
    }
    for (const tag of ["head", "hhea", "hmtx", "maxp", "loca", "glyf", "cmap", "fvar", "gvar", "GPOS"]) {
      if (!(tag in this.tables)) throw new Error(`font is missing the ${tag} table`);
    }
    if ("avar" in this.tables) throw new Error("avar axis remapping is not supported");
    this.unitsPerEm = this.u16(this.tables.head + 18);
    this.longLoca = this.i16(this.tables.head + 50) === 1;
    this.numGlyphs = this.u16(this.tables.maxp + 4);
    this.numberOfHMetrics = this.u16(this.tables.hhea + 34);
    this.axes = this.readAxes();
    this.cmap = this.readCmap();
    this.kerning = this.readKerning();
  }

  u8(at) { return this.data.getUint8(at); }
  i8(at) { return this.data.getInt8(at); }
  u16(at) { return this.data.getUint16(at); }
  i16(at) { return this.data.getInt16(at); }
  u32(at) { return this.data.getUint32(at); }
  f2dot14(at) { return this.i16(at) / 16384; }

  readAxes() {
    const base = this.tables.fvar, axesOffset = this.u16(base + 4), count = this.u16(base + 8), size = this.u16(base + 10);
    const axes = [];
    for (let i = 0; i < count; i++) {
      const at = base + axesOffset + i * size;
      const tag = String.fromCharCode(...[0, 1, 2, 3].map((k) => this.u8(at + k)));
      axes.push({ tag, min: this.u32(at + 4) / 65536, default: this.u32(at + 8) / 65536, max: this.u32(at + 12) / 65536 });
    }
    return axes;
  }

  // Normalized coordinates in [-1, 1] per axis, as the variation tables expect without avar.
  normalize(location) {
    return this.axes.map((axis) => {
      const value = Math.min(axis.max, Math.max(axis.min, location[axis.tag] ?? axis.default));
      if (value === axis.default) return 0;
      return value < axis.default ? (value - axis.default) / (axis.default - axis.min) : (value - axis.default) / (axis.max - axis.default);
    });
  }

  readCmap() {
    const base = this.tables.cmap, count = this.u16(base + 2);
    let format4 = null;
    for (let i = 0; i < count; i++) {
      const platform = this.u16(base + 4 + i * 8), encoding = this.u16(base + 6 + i * 8), at = base + this.u32(base + 8 + i * 8);
      const format = this.u16(at);
      if (format === 12 && (platform === 3 && encoding === 10 || platform === 0)) return this.cmap12(at);
      if (format === 4 && (platform === 3 && encoding === 1 || platform === 0)) format4 = at;
    }
    if (format4 === null) throw new Error("font has no Unicode cmap subtable");
    return this.cmap4(format4);
  }

  cmap4(at) {
    const segments = this.u16(at + 6) / 2, ends = at + 14, starts = ends + segments * 2 + 2;
    const deltas = starts + segments * 2, ranges = deltas + segments * 2;
    return (code) => {
      for (let i = 0; i < segments; i++) {
        if (code > this.u16(ends + i * 2)) continue;
        const start = this.u16(starts + i * 2);
        if (code < start) return 0;
        const delta = this.i16(deltas + i * 2), range = this.u16(ranges + i * 2);
        if (range === 0) return (code + delta) & 0xffff;
        const glyph = this.u16(ranges + i * 2 + range + (code - start) * 2);
        return glyph === 0 ? 0 : (glyph + delta) & 0xffff;
      }
      return 0;
    };
  }

  cmap12(at) {
    const groups = this.u32(at + 12);
    return (code) => {
      for (let i = 0; i < groups; i++) {
        const g = at + 16 + i * 12, start = this.u32(g), end = this.u32(g + 4);
        if (code >= start && code <= end) return this.u32(g + 8) + code - start;
      }
      return 0;
    };
  }

  glyphId(char) {
    const id = this.cmap(char.codePointAt(0));
    if (id === 0) throw new Error(`font has no glyph for ${JSON.stringify(char)}`);
    return id;
  }

  advance(glyph) {
    const index = Math.min(glyph, this.numberOfHMetrics - 1);
    return this.u16(this.tables.hmtx + index * 4);
  }

  leftSideBearing(glyph) {
    if (glyph < this.numberOfHMetrics) return this.i16(this.tables.hmtx + glyph * 4 + 2);
    return this.i16(this.tables.hmtx + this.numberOfHMetrics * 4 + (glyph - this.numberOfHMetrics) * 2);
  }

  glyphRange(glyph) {
    const loca = this.tables.loca;
    const at = (i) => (this.longLoca ? this.u32(loca + i * 4) : this.u16(loca + i * 2) * 2);
    return [this.tables.glyf + at(glyph), this.tables.glyf + at(glyph + 1)];
  }

  // The default-instance outline: contour end indices and points with on-curve flags.
  readGlyph(glyph) {
    const [start, end] = this.glyphRange(glyph);
    if (start === end) return { ends: [], points: [], xMin: 0 };
    const contours = this.i16(start);
    if (contours < 0) throw new Error(`glyph ${glyph} is a composite glyph, which brand text does not support`);
    const xMin = this.i16(start + 2);
    const ends = [];
    for (let i = 0; i < contours; i++) ends.push(this.u16(start + 10 + i * 2));
    const total = contours ? ends[contours - 1] + 1 : 0;
    let at = start + 10 + contours * 2;
    at += 2 + this.u16(at);
    const flags = [];
    while (flags.length < total) {
      const flag = this.u8(at++);
      flags.push(flag);
      if (flag & REPEAT) for (let r = this.u8(at++); r > 0; r--) flags.push(flag);
    }
    const coordinate = (short, same) => {
      const values = [];
      let value = 0;
      for (const flag of flags) {
        if (flag & short) { const d = this.u8(at++); value += flag & same ? d : -d; }
        else if (!(flag & same)) { value += this.i16(at); at += 2; }
        values.push(value);
      }
      return values;
    };
    const xs = coordinate(X_SHORT, X_SAME), ys = coordinate(Y_SHORT, Y_SAME);
    return { ends, xMin, points: flags.map((flag, i) => ({ x: xs[i], y: ys[i], on: Boolean(flag & ON_CURVE) })) };
  }

  // Applies gvar deltas for `coords`, returning the outline and advance at that instance.
  instance(glyph, coords) {
    const base = this.readGlyph(glyph);
    const origin = base.xMin - this.leftSideBearing(glyph);
    const points = [...base.points.map((p) => ({ ...p })), { x: origin, y: 0 }, { x: origin + this.advance(glyph), y: 0 }, { x: 0, y: 0 }, { x: 0, y: 0 }];
    const deltas = this.glyphDeltas(glyph, coords, base, points.length);
    points.forEach((p, i) => { p.x += deltas[i][0]; p.y += deltas[i][1]; });
    const phantom = points.splice(-4);
    return { ends: base.ends, points: points.map((p) => ({ x: p.x - phantom[0].x, y: p.y, on: p.on })), advance: Math.round(phantom[1].x - phantom[0].x) };
  }

  glyphDeltas(glyph, coords, base, count) {
    const totals = Array.from({ length: count }, () => [0, 0]);
    if (coords.every((c) => c === 0)) return totals;
    const gvar = this.tables.gvar, axisCount = this.u16(gvar + 4);
    const sharedTuples = gvar + this.u32(gvar + 8), longOffsets = this.u16(gvar + 14) & 1;
    const dataStart = gvar + this.u32(gvar + 16);
    const offset = (i) => (longOffsets ? this.u32(gvar + 20 + i * 4) : this.u16(gvar + 20 + i * 2) * 2);
    const start = dataStart + offset(glyph), end = dataStart + offset(glyph + 1);
    if (start === end) return totals;

    const header = this.u16(start);
    let serialized = start + this.u16(start + 2);
    let at = start + 4;
    let shared = null;
    if (header & SHARED_POINTS) [shared, serialized] = this.readPoints(serialized);
    for (let t = 0; t < (header & COUNT_MASK); t++) {
      const size = this.u16(at), index = this.u16(at + 2);
      at += 4;
      const tuple = (from) => Array.from({ length: axisCount }, (_, a) => this.f2dot14(from + a * 2));
      let peak;
      if (index & EMBEDDED_PEAK) { peak = tuple(at); at += axisCount * 2; }
      else peak = tuple(sharedTuples + (index & INDEX_MASK) * axisCount * 2);
      let lower = null, upper = null;
      if (index & INTERMEDIATE) { lower = tuple(at); upper = tuple(at + axisCount * 2); at += axisCount * 4; }
      const scalar = tupleScalar(coords, peak, lower, upper);
      const next = serialized + size;
      if (scalar !== 0) {
        let cursor = serialized, ids = shared;
        if (index & PRIVATE_POINTS) [ids, cursor] = this.readPoints(cursor);
        const n = ids === null ? count : ids.length;
        let xs, ys;
        [xs, cursor] = this.readDeltas(cursor, n);
        [ys] = this.readDeltas(cursor, n);
        const tupleDeltas = ids === null
          ? xs.map((x, i) => [x, ys[i]])
          : interpolateUntouched(base, count, ids, xs, ys);
        tupleDeltas.forEach(([x, y], i) => { totals[i][0] += x * scalar; totals[i][1] += y * scalar; });
      }
      serialized = next;
    }
    return totals;
  }

  // Packed point numbers; null means every point in the glyph.
  readPoints(at) {
    let count = this.u8(at++);
    if (count === 0) return [null, at];
    if (count & POINTS_WORDS) count = ((count & POINT_RUN_MASK) << 8) | this.u8(at++);
    const ids = [];
    let value = 0;
    while (ids.length < count) {
      const control = this.u8(at++), words = control & POINTS_WORDS;
      for (let run = (control & POINT_RUN_MASK) + 1; run > 0 && ids.length < count; run--) {
        value += words ? this.u16(at) : this.u8(at);
        at += words ? 2 : 1;
        ids.push(value);
      }
    }
    return [ids, at];
  }

  readDeltas(at, count) {
    const values = [];
    while (values.length < count) {
      const control = this.u8(at++), run = (control & DELTA_RUN_MASK) + 1;
      for (let r = 0; r < run && values.length < count; r++) {
        if (control & DELTAS_ZERO) values.push(0);
        else if (control & DELTAS_WORDS) { values.push(this.i16(at)); at += 2; }
        else values.push(this.i8(at++));
      }
    }
    return [values, at];
  }

  // GPOS pair adjustment from the kern feature of the latn (else DFLT) default language system.
  readKerning() {
    const gpos = this.tables.GPOS, scripts = gpos + this.u16(gpos + 4), features = gpos + this.u16(gpos + 6), lookups = gpos + this.u16(gpos + 8);
    const scriptTags = new Map();
    for (let i = 0; i < this.u16(scripts); i++) {
      const at = scripts + 2 + i * 6;
      scriptTags.set(String.fromCharCode(...[0, 1, 2, 3].map((k) => this.u8(at + k))), scripts + this.u16(at + 4));
    }
    const script = scriptTags.get("latn") ?? scriptTags.get("DFLT");
    if (script === undefined) return [];
    const langSys = script + this.u16(script);
    const featureIndices = Array.from({ length: this.u16(langSys + 4) }, (_, i) => this.u16(langSys + 6 + i * 2));
    const lookupIndices = new Set();
    for (const index of featureIndices) {
      const at = features + 2 + index * 6;
      const tag = String.fromCharCode(...[0, 1, 2, 3].map((k) => this.u8(at + k)));
      if (tag !== "kern") continue;
      const feature = features + this.u16(at + 4);
      for (let i = 0; i < this.u16(feature + 2); i++) lookupIndices.add(this.u16(feature + 4 + i * 2));
    }
    return [...lookupIndices].sort((a, b) => a - b).map((index) => {
      const lookup = lookups + this.u16(lookups + 2 + index * 2);
      if (this.u16(lookup) !== 2) throw new Error(`kern lookup ${index} is not a pair adjustment`);
      return Array.from({ length: this.u16(lookup + 4) }, (_, i) => this.pairSubtable(lookup + this.u16(lookup + 6 + i * 2)));
    });
  }

  pairSubtable(at) {
    const format = this.u16(at), coverage = this.coverage(at + this.u16(at + 2));
    const format1 = this.u16(at + 4), format2 = this.u16(at + 6);
    if (format1 & ~0x0004 || format2 !== 0) throw new Error("only x-advance pair kerning is supported");
    const recordSize = format1 & 0x0004 ? 2 : 0;
    if (format === 1) {
      return (left, right) => {
        const ci = coverage(left);
        if (ci < 0) return null;
        const set = at + this.u16(at + 10 + ci * 2);
        for (let i = 0; i < this.u16(set); i++) {
          const record = set + 2 + i * (2 + recordSize);
          if (this.u16(record) === right) return recordSize ? this.i16(record + 2) : 0;
        }
        return null;
      };
    }
    if (format === 2) {
      const class1 = this.classDef(at + this.u16(at + 8)), class2 = this.classDef(at + this.u16(at + 10));
      const class2Count = this.u16(at + 14);
      return (left, right) => {
        if (coverage(left) < 0) return null;
        const record = at + 16 + (class1(left) * class2Count + class2(right)) * recordSize;
        return recordSize ? this.i16(record) : 0;
      };
    }
    throw new Error(`unsupported pair adjustment format ${format}`);
  }

  coverage(at) {
    const format = this.u16(at), count = this.u16(at + 2);
    return (glyph) => {
      if (format === 1) {
        for (let i = 0; i < count; i++) if (this.u16(at + 4 + i * 2) === glyph) return i;
      } else {
        for (let i = 0; i < count; i++) {
          const r = at + 4 + i * 6;
          if (glyph >= this.u16(r) && glyph <= this.u16(r + 2)) return this.u16(r + 4) + glyph - this.u16(r);
        }
      }
      return -1;
    };
  }

  classDef(at) {
    const format = this.u16(at);
    return (glyph) => {
      if (format === 1) {
        const first = this.u16(at + 2), count = this.u16(at + 4);
        return glyph >= first && glyph < first + count ? this.u16(at + 6 + (glyph - first) * 2) : 0;
      }
      for (let i = 0; i < this.u16(at + 2); i++) {
        const r = at + 4 + i * 6;
        if (glyph >= this.u16(r) && glyph <= this.u16(r + 2)) return this.u16(r + 4);
      }
      return 0;
    };
  }

  // Each kern lookup applies once per pair; within a lookup the first matching subtable wins.
  kern(left, right) {
    let total = 0;
    for (const subtables of this.kerning) {
      for (const subtable of subtables) {
        const value = subtable(left, right);
        if (value !== null) { total += value; break; }
      }
    }
    return total;
  }

  // Lays out `text` at a location and returns glyph ids, outlines, and pen positions in font units.
  layout(text, location) {
    const coords = this.normalize(location);
    const glyphs = [...text].map((char) => this.glyphId(char));
    let x = 0;
    return glyphs.map((glyph, i) => {
      const outline = this.instance(glyph, coords);
      const placed = { glyph, x, advance: outline.advance, outline };
      x += outline.advance + (i + 1 < glyphs.length ? this.kern(glyph, glyphs[i + 1]) : 0);
      return placed;
    });
  }
}

// The tuple's region scalar at `coords`. Without an intermediate region the support runs
// from zero to the peak on each axis.
function tupleScalar(coords, peak, lower, upper) {
  let scalar = 1;
  for (let a = 0; a < coords.length; a++) {
    const p = peak[a];
    if (p === 0) continue;
    const lo = lower ? lower[a] : Math.min(0, p), hi = upper ? upper[a] : Math.max(0, p);
    if (lo > p || p > hi || (lo < 0 && hi > 0)) continue;
    const c = coords[a];
    if (c === p) continue;
    if (c <= lo || hi <= c) return 0;
    scalar *= c < p ? (c - lo) / (p - lo) : (c - hi) / (p - hi);
  }
  return scalar;
}

// Infers deltas for points a tuple leaves out (OpenType "IUP"): within each contour, an
// untouched point between two touched points interpolates their deltas by its default
// position, or copies the nearer delta when it lies outside them. Phantom points get zero.
function interpolateUntouched(base, count, ids, xs, ys) {
  const deltas = Array.from({ length: count }, () => [0, 0]);
  const touched = new Array(count).fill(false);
  ids.forEach((id, i) => { deltas[id] = [xs[i], ys[i]]; touched[id] = true; });
  let first = 0;
  for (const last of base.ends) {
    const marks = [];
    for (let i = first; i <= last; i++) if (touched[i]) marks.push(i);
    if (marks.length > 0 && marks.length < last - first + 1) {
      marks.forEach((a, k) => {
        const b = marks[(k + 1) % marks.length];
        for (let p = a === last ? first : a + 1; p !== b; p = p === last ? first : p + 1) {
          for (const [axis, key] of [[0, "x"], [1, "y"]]) {
            const pa = base.points[a][key], pb = base.points[b][key], v = base.points[p][key];
            const da = deltas[a][axis], db = deltas[b][axis];
            if (pa === pb) { deltas[p][axis] = da === db ? da : 0; continue; }
            const [lo, hi, dlo, dhi] = pa < pb ? [pa, pb, da, db] : [pb, pa, db, da];
            deltas[p][axis] = v <= lo ? dlo : v >= hi ? dhi : dlo + ((v - lo) / (hi - lo)) * (dhi - dlo);
          }
        }
      });
    }
    first = last + 1;
  }
  return deltas;
}

// One SVG path for `runs` set on a shared baseline at the origin. Each run is
// { text, weight, size, tracking } with size in px and tracking in em.
export function outlineText(font, runs) {
  const commands = [];
  let pen = 0;
  for (const run of runs) {
    const scale = run.size / font.unitsPerEm, track = (run.tracking ?? 0) * run.size;
    const laid = font.layout(run.text, { wght: run.weight });
    laid.forEach((placed, i) => {
      const x0 = pen + placed.x * scale + i * track;
      commands.push(contourPath(placed.outline, (p) => [x0 + p.x * scale, -p.y * scale]));
    });
    const last = laid[laid.length - 1];
    pen += (last.x + last.advance) * scale + (laid.length - 1) * track;
  }
  return { d: commands.filter(Boolean).join(""), width: round(pen) };
}

const round = (value) => Math.round(value * 100) / 100;
const fmt = (value) => { const s = round(value).toString(); return s === "-0" ? "0" : s; };

function contourPath(outline, project) {
  let out = "", first = 0;
  for (const last of outline.ends) {
    const pts = outline.points.slice(first, last + 1);
    first = last + 1;
    if (pts.length === 0) continue;
    const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, on: true });
    let startIndex = pts.findIndex((p) => p.on);
    let start;
    if (startIndex < 0) { start = mid(pts[0], pts[1]); startIndex = 0; }
    else start = pts[startIndex];
    const xy = (p) => project(p).map(fmt).join(" ");
    out += `M${xy(start)}`;
    let control = null;
    for (let k = 1; k <= pts.length; k++) {
      const p = k === pts.length && pts[startIndex] === start ? start : pts[(startIndex + k) % pts.length];
      if (p.on) {
        out += control ? `Q${xy(control)} ${xy(p)}` : `L${xy(p)}`;
        control = null;
      } else {
        if (control) out += `Q${xy(control)} ${xy(mid(control, p))}`;
        control = p;
      }
    }
    if (control) out += `Q${xy(control)} ${xy(start)}`;
    out += "Z";
  }
  return out;
}
