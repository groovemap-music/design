// SPDX-License-Identifier: MIT

import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outputRoot = join(root, "dist", "design");
const check = process.argv.includes("--check");
const checksumEntries = (await readFile(join(root, "brand", "assets.sha256"), "utf8")).trim().split("\n");
const sources = checksumEntries.map((entry) => {
  const [, expected, sourcePath] = entry.match(/^([a-f0-9]{64})  (brand\/assets\/[a-z0-9.-]+)$/) ?? [];
  if (!sourcePath) throw new Error(`Invalid asset checksum entry: ${entry}`);
  return { sourcePath, packagePath: `brand/${basename(sourcePath)}`, expected };
});
for (const sourcePath of ["LICENSE", "NOTICE", "TRADEMARKS.md"]) {
  sources.push({ sourcePath, packagePath: sourcePath, expected: null });
}

const expectedFiles = new Map();
const manifestFiles = [];
for (const { sourcePath, packagePath, expected } of sources) {
  const content = await readFile(join(root, sourcePath));
  const actual = createHash("sha256").update(content).digest("hex");
  if (expected !== null && actual !== expected) throw new Error(`Asset checksum differs: ${sourcePath}`);
  expectedFiles.set(packagePath, content);
  manifestFiles.push({ path: packagePath, sha256: actual, bytes: content.byteLength });
}
const manifest = Buffer.from(`${JSON.stringify({ schema_version: 1, license: "MIT", files: manifestFiles }, null, 2)}\n`);
expectedFiles.set("manifest.json", manifest);

async function listFiles(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await listFiles(path));
    else if (entry.isFile()) files.push(relative(outputRoot, path));
  }
  return files.sort();
}

if (check) {
  const existingPaths = await listFiles(outputRoot).catch(() => []);
  const expectedPaths = [...expectedFiles.keys()].sort();
  if (JSON.stringify(existingPaths) !== JSON.stringify(expectedPaths)) {
    throw new Error("Built design package contains missing or unexpected files. Run 'just build'.");
  }
  for (const [path, expected] of expectedFiles) {
    const actual = await readFile(join(outputRoot, path));
    if (!actual.equals(expected)) throw new Error(`Built design package differs: ${path}`);
  }
  console.log(`Verified a deterministic package containing ${manifestFiles.length} licensed files.`);
} else {
  await rm(outputRoot, { recursive: true, force: true });
  for (const [path, content] of expectedFiles) {
    const outputPath = join(outputRoot, path);
    await mkdir(dirname(outputPath), { recursive: true });
    await writeFile(outputPath, content);
  }
  console.log(`Built a deterministic package containing ${manifestFiles.length} licensed files.`);
}
