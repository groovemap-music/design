// SPDX-License-Identifier: MIT

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { ROOT } from "../scripts/tooling.mjs";
import { loadFont, outlineText } from "./font.mjs";
import { markBody } from "./mark.mjs";

const root = join(ROOT, "brand");
const assetsDir = join(root, "assets");
const check = process.argv.includes("--check");
const tokens = JSON.parse(await readFile(join(root, "tokens.json"), "utf8"));
const font = loadFont(join(root, tokens.type.file));

const escapeXml = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const RAW = new Set(["MARK_BODY", "WORDMARK_PATH", "TAGLINE_PATH", "DESCRIPTOR_PATH", "DOMAIN_PATH"]);
const render = (template, values) => template.replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, key) => {
  if (!(key in values)) throw new Error(`Missing template value: ${key}`);
  if (RAW.has(key)) return values[key];
  return escapeXml(values[key]);
});

const [markTemplate, bannerTemplate, ogTemplate] = await Promise.all([
  "mark.svg.tmpl",
  "banner.svg.tmpl",
  "og.svg.tmpl",
].map((name) => readFile(join(root, "templates", name), "utf8")));

// Brand text is outlined from the vendored font at the px size each layout draws it.
const weight = tokens.type.weight;
const outline = (text, textWeight, size, tracking = 0) => outlineText(font, [{ text, weight: textWeight, size, tracking }]).d;
const bannerText = {
  WORDMARK_PATH: outline(tokens.brand.wordmark, weight.wordmark, 140),
  TAGLINE_PATH: outline(tokens.brand.tagline, weight.tagline, 38),
};
const ogText = {
  WORDMARK_PATH: outline(tokens.brand.wordmark, weight.wordmark, 120),
  DESCRIPTOR_PATH: outline(tokens.brand.descriptor, weight.descriptor, 40),
  DOMAIN_PATH: outline(tokens.brand.domain, weight.domain, 30, 0.02),
};

const shared = {
  DISPLAY_NAME: tokens.brand.displayName,
  TAGLINE: tokens.brand.tagline,
  DEEP: tokens.color.deep,
};

// The light pin is mint with a lagoon outline so it stays distinct from the lagoon nodes.
const theme = {
  dark: {
    BACKGROUND: tokens.color.void, TEXT: tokens.color.text, MUTED_TEXT: tokens.color.mutedText, ACCENT: tokens.color.mint,
    mark: { background: tokens.color.void, accent: tokens.color.mint, pinFill: tokens.color.text, pinStroke: tokens.color.void },
  },
  light: {
    BACKGROUND: tokens.color.lightBackground, TEXT: tokens.color.lightText, MUTED_TEXT: tokens.color.lightMutedText, ACCENT: tokens.color.lagoon,
    mark: { background: tokens.color.lightBackground, accent: tokens.color.lagoon, pinFill: tokens.color.mint, pinStroke: tokens.color.lagoon },
  },
};

const icon = (variant, size, radius, small = false) => render(markTemplate, {
  ...shared, ...theme[variant], WIDTH: size, HEIGHT: size, RADIUS: radius, MARK_BODY: markBody(theme[variant].mark, { small }),
});
const banner = (variant, width, height) => render(bannerTemplate, {
  ...shared, ...theme[variant], ...bannerText, WIDTH: width, HEIGHT: height, MARK_BODY: markBody(theme[variant].mark),
});

const outputs = new Map();
for (const variant of ["dark", "light"]) {
  outputs.set(`icon-${variant}.svg`, icon(variant, 1024, 0));
  outputs.set(`banner-${variant}.svg`, banner(variant, 1600, 400));
}

// Radii are in the mark's 100-unit box: 9.38 matches the former 96/1024 avatar corner and
// 12.5 the former 128/1024 app-icon corner. Favicons use the simplified small mark.
outputs.set("avatar.svg", icon("dark", 512, 9.38));
outputs.set("favicon.svg", icon("dark", 64, 12.5, true));
outputs.set("app-icon-192.svg", icon("dark", 192, 12.5));
outputs.set("app-icon-512.svg", icon("dark", 512, 12.5));
outputs.set("og-image.svg", render(ogTemplate, { ...shared, ...theme.dark, ...ogText, WIDTH: 1200, HEIGHT: 630, MARK_BODY: markBody(theme.dark.mark) }));
outputs.set("social-banner.svg", banner("dark", 1500, 375));

const manifest = {
  name: tokens.brand.displayName,
  short_name: tokens.brand.displayName,
  description: tokens.brand.tagline,
  icons: [
    { src: "/brand/app-icon-192.svg", sizes: "192x192", type: "image/svg+xml" },
    { src: "/brand/app-icon-512.svg", sizes: "512x512", type: "image/svg+xml" },
  ],
  theme_color: tokens.color.void,
  background_color: tokens.color.void,
  display: "standalone",
};
outputs.set("site.webmanifest", `${JSON.stringify(manifest, null, 2)}\n`);

const kebab = (name) => name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
const cssVariables = [
  ...Object.entries(tokens.color).map(([name, value]) => [kebab(name), value]),
  ...Object.entries(tokens.entity).map(([name, value]) => [`entity-${kebab(name)}`, value]),
  ...Object.entries(tokens.state).flatMap(([vocabulary, states]) => Object.entries(states).flatMap(([name, themes]) => (
    Object.entries(themes).map(([themeName, value]) => [`state-${kebab(vocabulary)}-${kebab(name)}-${themeName}`, value])
  ))),
];
const cssLines = cssVariables.map(([name, value]) => `  --groovemap-${name}: ${value};`).join("\n");
outputs.set("tokens.css", `:root {\n${cssLines}\n}\n`);

await mkdir(assetsDir, { recursive: true });
const differences = [];
for (const [name, content] of outputs) {
  const path = join(assetsDir, name);
  if (check) {
    const existing = await readFile(path, "utf8").catch(() => null);
    if (existing !== content) differences.push(name);
  } else {
    await writeFile(path, content, "utf8");
  }
}

if (differences.length) {
  throw new Error(`Brand assets are stale or missing: ${differences.join(", ")}. Run 'just brand-render'.`);
}
console.log(check ? `Verified ${outputs.size} deterministic brand assets.` : `Rendered ${outputs.size} brand assets.`);
