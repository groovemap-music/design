// SPDX-License-Identifier: MIT

import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export function sha256(contents) {
  return createHash("sha256").update(contents).digest("hex");
}
