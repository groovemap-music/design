// SPDX-License-Identifier: MIT
// Static server for the harness with a strict Content-Security-Policy. Vendor files (and Playwright,
// for the measurement scripts) come from an npm prefix outside the repository; vendor files are
// served only if their SHA-256 matches the pin below.
//   node scripts/serve.mjs [port]   (VENDOR_PREFIX defaults to ~/.cache/groovemap-spikes/gm-design-on0x/node)

import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { join, normalize, extname, dirname } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const HERE = dirname(dirname(fileURLToPath(import.meta.url)));
export const PREFIX = process.env.VENDOR_PREFIX || join(homedir(), '.cache/groovemap-spikes/gm-design-on0x/node');
export const VENDOR = {
  'three.module.js': { path: 'node_modules/three/build/three.module.js', sha256: '9052042d676cb0fdc1ddfefe193053f34b7ac0513a616fdac4535d49987812ea', pkg: 'three@0.186.1' },
  'three.core.js': { path: 'node_modules/three/build/three.core.js', sha256: '9edde002b066a9a05676a6127f67735b62baf399bdea529f2f7e31657da769e6', pkg: 'three@0.186.1' },
  'd3.min.js': { path: 'node_modules/d3/dist/d3.min.js', sha256: 'f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539', pkg: 'd3@7.9.0' },
};
const TYPES = { '.html': 'text/html; charset=utf-8', '.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
const sha = (buf, enc = 'hex') => createHash('sha256').update(buf).digest(enc);

const vendor = new Map();
for (const [name, v] of Object.entries(VENDOR)) {
  const buf = readFileSync(join(PREFIX, v.path));
  if (sha(buf) !== v.sha256) throw new Error(`${name}: digest mismatch for ${v.pkg}`);
  vendor.set(name, buf);
}
// The importmap is an inline script, so a policy without 'unsafe-inline' must list its hash.
const html = readFileSync(join(HERE, 'web/index.html'), 'utf8');
const importmap = html.match(/<script type="importmap">([\s\S]*?)<\/script>/)[1];
export const CSP = `default-src 'self'; script-src 'self' 'sha256-${sha(importmap, 'base64')}'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`;

export function serve(port = 0) {
  const server = createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    let body = null, type = 'application/octet-stream';
    if (url.pathname.startsWith('/vendor/')) { body = vendor.get(url.pathname.slice(8)); type = 'text/javascript'; }
    else {
      const rel = normalize(url.pathname).replace(/^\/+/, '');
      if (/^(web|lib|results)\//.test(rel) && !rel.includes('..')) {
        const f = join(HERE, rel);
        if (existsSync(f)) { body = readFileSync(f); type = TYPES[extname(f)] || type; }
      }
    }
    if (!body) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': type, 'content-security-policy': CSP, 'cache-control': 'no-store' });
    res.end(body);
  });
  return new Promise((resolve) => server.listen(port, '127.0.0.1', () => resolve(server)));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const s = await serve(+(process.argv[2] || 8765));
  console.log(`http://127.0.0.1:${s.address().port}/web/index.html?r=webgl-inst&n=500`);
}
