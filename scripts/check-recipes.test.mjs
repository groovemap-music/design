// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { validateRecipeContract } from "./check-recipes.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const justfile = readFileSync(resolve(root, "Justfile"), "utf8");
const documentation = readFileSync(resolve(root, "README.md"), "utf8");

test("repository recipes satisfy shared and documented domain capabilities", () => {
  assert.deepEqual(validateRecipeContract(justfile, documentation), []);
});

test("recipe contract rejects undeclared and unresolved capabilities", () => {
  const invalid = `${justfile}\nunknown-check: missing-check\n`;
  const errors = validateRecipeContract(invalid, documentation);
  assert.ok(errors.includes("undeclared recipe capability: unknown-check"));
  assert.ok(errors.includes("unknown-check references missing recipe: missing-check"));
});

test("recipe contract requires a documented purpose for every domain capability", () => {
  const errors = validateRecipeContract(justfile, documentation.replace("| `catalog` |", "| `removed` |"));
  assert.ok(errors.includes("domain recipe purpose is undocumented: catalog"));
});

test("credential-free check excludes explicit generation and handoff commands", () => {
  for (const recipe of ["brand-render", "publication-readiness"]) {
    const invalid = justfile.replace(/^check: (.*)$/m, `check: $1 ${recipe}`);
    assert.ok(validateRecipeContract(invalid, documentation).includes(`credential-free check must not invoke explicit command: ${recipe}`));
  }
});

test("credential-free check retains every validation capability", () => {
  const invalid = justfile.replace(" catalog taxonomy", " taxonomy");
  assert.ok(validateRecipeContract(invalid, documentation).includes("check must retain the complete ordered credential-free capability set"));
});
