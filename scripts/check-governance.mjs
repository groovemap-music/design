// SPDX-License-Identifier: MIT

import { createHash } from "node:crypto";
import { access, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const required = ["README.md", "NOTICE", "TRADEMARKS.md", "CONTRIBUTING.md"];
const expectedLicenseHash = "9572d39cdc09c0b2cd792a14fef5dcc4ed1b955d9b1ea2a3d0c058221fa5f391";

const fail = (message) => {
  throw new Error(message);
};

const contents = Object.fromEntries(await Promise.all(required.map(async (path) => [
  path,
  await readFile(join(root, path), "utf8"),
])));

const license = await readFile(join(root, "LICENSE"));
const licenseHash = createHash("sha256").update(license).digest("hex");
if (licenseHash !== expectedLicenseHash) {
  fail(`LICENSE must remain the unmodified approved MIT text (got ${licenseHash}).`);
}

const expect = (path, patterns) => {
  for (const pattern of patterns) {
    if (!pattern.test(contents[path])) fail(`${path} is missing required guidance matching ${pattern}.`);
  }
};

expect("README.md", [/MIT License/i, /TRADEMARKS\.md/, /CONTRIBUTING\.md/, /just check/]);
expect("NOTICE", [/MIT License/i, /does not grant trademark rights/i, /respective contributor/i]);
expect("TRADEMARKS.md", [
  /separate from.*MIT copyright license/i,
  /truthfully refer/i,
  /community event/i,
  /source identifier/i,
  /sponsor(?:ed|ship).*endorse(?:d|ment)/i,
  /applicable law/i,
  /rights actually held/i,
]);
expect("CONTRIBUTING.md", [
  /MIT License/i,
  /copyright remains with the contributor/i,
  /authority to provide/i,
  /unknown provenance/i,
  /private operator paths/i,
  /just check/i,
]);

for (const [path, text] of Object.entries(contents)) {
  if (new RegExp(["discogs", "ography"].join(""), "i").test(text)) fail(`${path} contains the retired project name.`);
  if (/\/Users\//.test(text)) fail(`${path} contains an operator-specific path.`);
}

const brandReadme = await readFile(join(root, "brand", "README.md"), "utf8");
if (/brand\/legacy|`legacy\/`|\.\.\/docs\/README\.md/.test(brandReadme)) {
  fail("brand/README.md references excluded legacy or missing documentation.");
}
await access(join(root, "brand", "tokens.json"));

console.log(`Verified ${required.length} governance files and the unmodified MIT license.`);
