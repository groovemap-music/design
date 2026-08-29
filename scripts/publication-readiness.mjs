// SPDX-License-Identifier: MIT

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function git(...arguments_) {
  const result = spawnSync("git", arguments_, { cwd: root, encoding: "utf8" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`git ${arguments_.join(" ")} failed: ${result.stderr.trim()}`);
  return result.stdout.trim();
}

const status = git("status", "--porcelain", "--untracked-files=all");
if (status !== "") throw new Error("publication readiness requires a clean reviewed commit");

const catalogBytes = readFileSync(resolve(root, "catalog/repositories.json"));
const catalog = JSON.parse(catalogBytes.toString("utf8"));
if (catalog.schema_version !== 1 || catalog.repositories.length !== 20) {
  throw new Error("catalog identity changed after validation");
}

const handoff = {
  schema_version: 1,
  design_commit: git("rev-parse", "HEAD"),
  catalog_path: "catalog/repositories.json",
  catalog_sha256: createHash("sha256").update(catalogBytes).digest("hex"),
  catalog_repository_count: catalog.repositories.length,
  publication_action_performed: false,
};

process.stdout.write(`${JSON.stringify(handoff, null, 2)}\n`);
