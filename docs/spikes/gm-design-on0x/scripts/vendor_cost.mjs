// SPDX-License-Identifier: MIT
// What vendoring three.js into graph-explorer would add: bytes on the wire and on disk, digests for a
// source.json pin, the license text digest for ASSET_LICENSES, and the constructs a strict
// Content-Security-Policy would block.
//   node scripts/vendor_cost.mjs > results/vendoring.json

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync, brotliCompressSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { PREFIX, VENDOR } from './serve.mjs';

const sha = (b) => createHash('sha256').update(b).digest('hex');
const CSP_RISKS = { eval: /\beval\s*\(/g, newFunction: /new\s+Function\s*\(/g, stringTimer: /set(?:Timeout|Interval)\s*\(\s*['"`]/g, blobUrl: /URL\.createObjectURL/g, worker: /new\s+(?:Shared)?Worker\s*\(/g, wasm: /WebAssembly\./g };
const files = Object.entries(VENDOR).map(([name, v]) => {
  const buf = readFileSync(join(PREFIX, v.path));
  const text = buf.toString('utf8');
  return {
    name, package: v.pkg, bytes: buf.length, gzip9: gzipSync(buf, { level: 9 }).length, brotli: brotliCompressSync(buf).length, sha256: sha(buf),
    cspRisks: Object.fromEntries(Object.entries(CSP_RISKS).map(([k, re]) => [k, (text.match(re) || []).length])),
    bareImports: [...new Set([...text.matchAll(/(?:^|[\s;])(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]/g)].map((m) => m[1]))],
  };
});
const pkg = (name) => JSON.parse(readFileSync(join(PREFIX, 'node_modules', name, 'package.json'), 'utf8'));
const lic = (name) => ({ license: pkg(name).license, version: pkg(name).version, licenseFileSha256: sha(readFileSync(join(PREFIX, 'node_modules', name, 'LICENSE'))) });
const three = files.filter((f) => f.package.startsWith('three@'));
console.log(JSON.stringify({
  files,
  three: { ...lic('three'), bytes: three.reduce((s, f) => s + f.bytes, 0), gzip9: three.reduce((s, f) => s + f.gzip9, 0), brotli: three.reduce((s, f) => s + f.brotli, 0) },
  d3: lic('d3'),
}, null, 1));
