// SPDX-License-Identifier: MIT

// Checks the Strata state-color tokens in brand/tokens.json (ADR 0016 section 4).
// Color-as-state must not be mistaken for an entity-type color, and every state must stay
// readable on the backgrounds it is drawn on, in both themes.

export const THEMES = ["light", "dark"];

// WCAG 2.x AA for normal text. Strata draws state labels beside nodes, so every state color
// meets the text threshold, which also exceeds the 3:1 non-text threshold for the node fill.
export const MIN_CONTRAST = 4.5;

// CIEDE2000 distances. A state must sit at least MIN_ENTITY_DELTA_E from every entity-type
// color and brand accent. States drawn together must sit at least MIN_PEER_DELTA_E apart.
export const MIN_ENTITY_DELTA_E = 15;
export const MIN_PEER_DELTA_E = 15;

// The backgrounds a state is drawn on. Dark nodes sit on the canvas (void) or a card (deep).
// A light fill on the paler light canvas is the lowest-contrast case for a white card too.
export const BACKGROUNDS = {
  dark: ["void", "deep"],
  light: ["lightBackground"],
};

// Sets that appear in one view, so their members must stay distinguishable from each other.
// C' is drawn on B's atlas, so its components must also differ from B's stages.
export const PEER_GROUPS = {
  collector: ["collector"],
  lifecycle: ["lifecycle"],
  fit: ["fit", "lifecycle"],
  identity: ["identity"],
};

// ADR 0016 section 4: the closed state vocabularies.
export const STATE_VOCABULARIES = {
  collector: ["none", "wanted", "owned", "wantedOwned"],
  lifecycle: ["absent", "emerging", "established", "reviving", "declining", "provisional"],
  fit: ["affinity", "novelty", "bridge", "redundancy"],
  identity: ["notRecorded", "discogsOnly", "musicbrainzOnly", "unresolved", "split", "linked", "superseded"],
};

const HEX = /^#[0-9a-f]{6}$/;

export function parseHex(value) {
  if (typeof value !== "string" || !HEX.test(value)) throw new Error(`not a lowercase #rrggbb color: ${value}`);
  return [1, 3, 5].map((i) => Number.parseInt(value.slice(i, i + 2), 16));
}

const linear = (channel) => {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};

export function relativeLuminance(hex) {
  const [r, g, b] = parseHex(hex).map(linear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(foreground, background) {
  const [a, b] = [relativeLuminance(foreground), relativeLuminance(background)];
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function toLab(hex) {
  const [r, g, b] = parseHex(hex).map(linear);
  const x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047;
  const y = 0.2126729 * r + 0.7151522 * g + 0.072175 * b;
  const z = (0.0193339 * r + 0.119192 * g + 0.9503041 * b) / 1.08883;
  const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

const rad = (degrees) => (degrees * Math.PI) / 180;
const deg = (radians) => ((radians * 180) / Math.PI + 360) % 360;

// CIEDE2000 (Sharma, Wu, and Dalal's reference formulation, kL = kC = kH = 1).
export function deltaE2000Lab([L1, a1, b1], [L2, a2, b2]) {
  const meanC = (Math.hypot(a1, b1) + Math.hypot(a2, b2)) / 2;
  const g = 0.5 * (1 - Math.sqrt(meanC ** 7 / (meanC ** 7 + 25 ** 7)));
  const [ap1, ap2] = [(1 + g) * a1, (1 + g) * a2];
  const [C1, C2] = [Math.hypot(ap1, b1), Math.hypot(ap2, b2)];
  const [h1, h2] = [C1 === 0 ? 0 : deg(Math.atan2(b1, ap1)), C2 === 0 ? 0 : deg(Math.atan2(b2, ap2))];
  const dL = L2 - L1;
  const dC = C2 - C1;
  let dh = 0;
  if (C1 * C2 !== 0) {
    dh = h2 - h1;
    if (dh > 180) dh -= 360;
    else if (dh < -180) dh += 360;
  }
  const dH = 2 * Math.sqrt(C1 * C2) * Math.sin(rad(dh / 2));
  const meanL = (L1 + L2) / 2;
  const meanCp = (C1 + C2) / 2;
  let meanH = h1 + h2;
  if (C1 * C2 !== 0) {
    meanH = Math.abs(h1 - h2) <= 180 ? (h1 + h2) / 2 : h1 + h2 < 360 ? (h1 + h2 + 360) / 2 : (h1 + h2 - 360) / 2;
  }
  const t = 1 - 0.17 * Math.cos(rad(meanH - 30)) + 0.24 * Math.cos(rad(2 * meanH)) + 0.32 * Math.cos(rad(3 * meanH + 6)) - 0.2 * Math.cos(rad(4 * meanH - 63));
  const sL = 1 + (0.015 * (meanL - 50) ** 2) / Math.sqrt(20 + (meanL - 50) ** 2);
  const sC = 1 + 0.045 * meanCp;
  const sH = 1 + 0.015 * meanCp * t;
  const rT = -2 * Math.sqrt(meanCp ** 7 / (meanCp ** 7 + 25 ** 7)) * Math.sin(rad(60 * Math.exp(-(((meanH - 275) / 25) ** 2))));
  return Math.sqrt((dL / sL) ** 2 + (dC / sC) ** 2 + (dH / sH) ** 2 + rT * (dC / sC) * (dH / sH));
}

export const deltaE2000 = (first, second) => deltaE2000Lab(toLab(first), toLab(second));

function flatten(tokens) {
  const entity = tokens.entity ?? {};
  const accents = Object.fromEntries(["mint", "lagoon"].map((name) => [name, tokens.color?.[name]]));
  return { entity: { ...entity, ...Object.fromEntries(Object.entries(accents).map(([name, value]) => [`brand.${name}`, value])) } };
}

// Returns a list of problems. An empty list means the tokens are valid.
export function validateStateTokens(tokens) {
  const errors = [];
  const state = tokens.state ?? {};
  const { entity } = flatten(tokens);

  for (const [name, value] of Object.entries(entity)) {
    try {
      parseHex(value);
    } catch (error) {
      errors.push(`entity color ${name}: ${error.message}`);
    }
  }
  if (errors.length) return errors;

  for (const [vocabulary, names] of Object.entries(STATE_VOCABULARIES)) {
    const actual = Object.keys(state[vocabulary] ?? {});
    if (actual.join(",") !== names.join(",")) errors.push(`state.${vocabulary} must hold exactly ${names.join(", ")} in order, found ${actual.join(", ")}`);
  }
  if (Object.keys(state).join(",") !== Object.keys(STATE_VOCABULARIES).join(",")) errors.push("state must hold exactly the ADR 0016 vocabularies in order");
  if (errors.length) return errors;

  const value = (vocabulary, name, theme) => state[vocabulary][name][theme];
  for (const [vocabulary, names] of Object.entries(STATE_VOCABULARIES)) {
    for (const name of names) {
      const token = state[vocabulary][name];
      if (Object.keys(token).join(",") !== THEMES.join(",")) errors.push(`state.${vocabulary}.${name} must hold exactly ${THEMES.join(" and ")} values`);
      for (const theme of THEMES) {
        try {
          parseHex(token[theme]);
        } catch (error) {
          errors.push(`state.${vocabulary}.${name}.${theme}: ${error.message}`);
        }
      }
    }
  }
  if (errors.length) return errors;

  for (const [vocabulary, names] of Object.entries(STATE_VOCABULARIES)) {
    for (const name of names) {
      for (const theme of THEMES) {
        const color = value(vocabulary, name, theme);
        for (const background of BACKGROUNDS[theme]) {
          const ratio = contrastRatio(color, tokens.color[background]);
          if (ratio < MIN_CONTRAST) errors.push(`state.${vocabulary}.${name}.${theme} ${color} has contrast ${ratio.toFixed(2)} on ${background}, below ${MIN_CONTRAST}`);
        }
        for (const [entityName, entityColor] of Object.entries(entity)) {
          const distance = deltaE2000(color, entityColor);
          if (distance < MIN_ENTITY_DELTA_E) errors.push(`state.${vocabulary}.${name}.${theme} ${color} is within ${distance.toFixed(1)} of ${entityName} ${entityColor}, below ${MIN_ENTITY_DELTA_E}`);
        }
      }
    }
  }

  for (const [view, groups] of Object.entries(PEER_GROUPS)) {
    const members = groups.flatMap((group) => STATE_VOCABULARIES[group].map((name) => [group, name]));
    for (const theme of THEMES) {
      for (const [i, [groupA, nameA]] of members.entries()) {
        for (const [groupB, nameB] of members.slice(i + 1)) {
          const distance = deltaE2000(value(groupA, nameA, theme), value(groupB, nameB, theme));
          if (distance < MIN_PEER_DELTA_E) errors.push(`${view} view: state.${groupA}.${nameA}.${theme} is within ${distance.toFixed(1)} of state.${groupB}.${nameB}.${theme}, below ${MIN_PEER_DELTA_E}`);
        }
      }
    }
  }
  return errors;
}
