// SPDX-License-Identifier: MIT

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const SHARED_RECIPES = new Set([
  "audit",
  "build",
  "check",
  "coverage",
  "default",
  "install-check",
  "license-check",
  "lint",
  "secret-scan",
  "setup",
  "test",
]);

const DOMAIN_RECIPES = new Set([
  "brand",
  "brand-render",
  "catalog",
  "links",
  "policy-check",
  "publication-readiness",
  "taxonomy",
]);

export function parseRecipes(source) {
  const recipes = new Map();
  const duplicates = new Set();
  for (const line of source.split("\n")) {
    const match = line.match(/^([a-z][a-z0-9-]*)(?:\s+[^:]*)?:(?!=)\s*(.*)$/);
    if (!match) continue;
    const [, name, dependencySource] = match;
    if (recipes.has(name)) duplicates.add(name);
    const dependencies = dependencySource.split(/\s+/).filter((value) => /^[a-z][a-z0-9-]*$/.test(value));
    recipes.set(name, dependencies);
  }
  return { recipes, duplicates };
}

export function validateRecipeContract(justfile, documentation) {
  const errors = [];
  const { recipes, duplicates } = parseRecipes(justfile);
  const allowed = new Set([...SHARED_RECIPES, ...DOMAIN_RECIPES]);

  for (const name of duplicates) errors.push(`duplicate recipe: ${name}`);
  for (const name of recipes.keys()) {
    if (!allowed.has(name)) errors.push(`undeclared recipe capability: ${name}`);
  }
  for (const name of allowed) {
    if (!recipes.has(name)) errors.push(`declared recipe is missing: ${name}`);
  }
  for (const [name, dependencies] of recipes) {
    for (const dependency of dependencies) {
      if (!recipes.has(dependency)) errors.push(`${name} references missing recipe: ${dependency}`);
    }
  }
  for (const name of DOMAIN_RECIPES) {
    if (!documentation.includes(`| \`${name}\` |`)) errors.push(`domain recipe purpose is undocumented: ${name}`);
  }

  const checkDependencies = recipes.get("check") ?? [];
  const expectedCheckDependencies = [
    "lint",
    "test",
    "policy-check",
    "links",
    "catalog",
    "taxonomy",
    "brand",
    "license-check",
    "audit",
    "secret-scan",
    "build",
    "install-check",
  ];
  if (JSON.stringify(checkDependencies) !== JSON.stringify(expectedCheckDependencies)) {
    errors.push("check must retain the complete ordered credential-free capability set");
  }
  for (const stateful of ["brand-render", "publication-readiness"]) {
    if (checkDependencies.includes(stateful)) errors.push(`credential-free check must not invoke explicit command: ${stateful}`);
  }
  if (!/^brand-render:\s*\n(?:    .*\n)*?    \{\{tool\}\} node brand\/render\.mjs\s*$/m.test(justfile)) {
    errors.push("brand-render must remain an explicit canonical source-generation command");
  }
  if (!/^publication-readiness:\s*\n    just check\s*\n    \{\{tool\}\} node scripts\/publication-readiness\.mjs\s*$/m.test(justfile)) {
    errors.push("publication-readiness must retain the complete local gate before its handoff");
  }

  return errors;
}

function run() {
  const justfile = readFileSync(resolve(root, "Justfile"), "utf8");
  const documentation = readFileSync(resolve(root, "README.md"), "utf8");
  const errors = validateRecipeContract(justfile, documentation);
  if (errors.length > 0) throw new Error(`recipe provider contract:\n- ${errors.join("\n- ")}`);
  console.log(`Verified ${SHARED_RECIPES.size} shared recipes and ${DOMAIN_RECIPES.size} documented design capabilities.`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) run();
