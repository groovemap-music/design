import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const assetsDir = join(root, "assets");
const check = process.argv.includes("--check");
const tokens = JSON.parse(await readFile(join(root, "tokens.json"), "utf8"));

const escapeXml = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const render = (template, values) => template.replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, key) => {
  if (!(key in values)) throw new Error(`Missing template value: ${key}`);
  if (key === "MARK_BODY") return values[key];
  return escapeXml(values[key]);
});

const [markTemplate, bannerTemplate, ogTemplate] = await Promise.all([
  "mark.svg.tmpl",
  "banner.svg.tmpl",
  "og.svg.tmpl",
].map((name) => readFile(join(root, "templates", name), "utf8")));

const shared = {
  DISPLAY_NAME: tokens.brand.displayName,
  DOMAIN: tokens.brand.domain,
  TAGLINE: tokens.brand.tagline,
  BORDER: tokens.color.border,
  CYAN: tokens.color.cyan,
  CYAN_GLOW: tokens.color.cyanGlow,
  DEEP: tokens.color.deep,
  MUTED_TEXT: tokens.color.mutedText,
  PURPLE: tokens.color.purple,
  PURPLE_LIGHT: tokens.color.purpleLight,
};

const theme = {
  dark: { BACKGROUND: tokens.color.void, TEXT: tokens.color.text },
  light: { BACKGROUND: tokens.color.lightBackground, TEXT: tokens.color.lightText },
};

const markBody = markTemplate
  .replace(/^<svg[^>]*>\n/, "")
  .replace(/<title[^>]*>.*?<\/title>\n/, "")
  .replace(/<\/svg>\s*$/, "");

const outputs = new Map();
for (const variant of ["dark", "light"]) {
  const values = { ...shared, ...theme[variant], WIDTH: 1024, HEIGHT: 1024, RADIUS: 0 };
  outputs.set(`icon-${variant}.svg`, render(markTemplate, values));
  outputs.set(`banner-${variant}.svg`, render(bannerTemplate, { ...values, WIDTH: 1600, HEIGHT: 400, MARK_BODY: render(markBody, values) }));
}

const dark = { ...shared, ...theme.dark, WIDTH: 512, HEIGHT: 512, RADIUS: 96 };
outputs.set("avatar.svg", render(markTemplate, dark));
outputs.set("favicon.svg", render(markTemplate, { ...dark, WIDTH: 64, HEIGHT: 64, RADIUS: 128 }));
outputs.set("app-icon-192.svg", render(markTemplate, { ...dark, WIDTH: 192, HEIGHT: 192, RADIUS: 128 }));
outputs.set("app-icon-512.svg", render(markTemplate, { ...dark, WIDTH: 512, HEIGHT: 512, RADIUS: 128 }));
outputs.set("og-image.svg", render(ogTemplate, { ...dark, WIDTH: 1200, HEIGHT: 630, MARK_BODY: render(markBody, dark) }));
outputs.set("social-banner.svg", render(bannerTemplate, { ...dark, WIDTH: 1500, HEIGHT: 375, MARK_BODY: render(markBody, dark) }));

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

const cssLines = Object.entries(tokens.color)
  .map(([name, value]) => `  --groovemap-${name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}: ${value};`)
  .join("\n");
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
