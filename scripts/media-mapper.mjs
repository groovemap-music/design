// SPDX-License-Identifier: MIT
//
// Reference mapper for ADR 0007. It proves the conformance fixtures under
// taxonomy/media/v1/fixtures against the vocabulary; every vendored mapper
// (Rust producers, Python runtime) must reproduce these outputs exactly.

const ITEM_ATTRIBUTES = new Set(["size_inches", "speed_rpm", "channels", "codec"]);
const ITEM_LISTS = { variant: "variants", appearance: "appearance" };
const RELEASE_LISTS = { trait: "traits", edition: "edition", flag: "flags" };

function sortedUnique(values) {
  return [...new Set(values)].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
}

function index(taxonomy) {
  return {
    families: new Map(taxonomy.families.map((family) => [family.id, family])),
    media: new Map(taxonomy.media.map((medium) => [medium.id, medium])),
  };
}

function emptyBlock(taxonomy) {
  return {
    taxonomy_version: taxonomy.taxonomy_version,
    items: [],
    families: [],
    release_kind: null,
    traits: [],
    edition: [],
    packaging: null,
    container: null,
    flags: [],
    unmapped: { formats: [], descriptions: [] },
  };
}

function newItem(provider, name, descriptions, text) {
  return {
    family: null,
    medium: null,
    qty: 1,
    size_inches: null,
    speed_rpm: null,
    channels: null,
    codec: null,
    variants: [],
    appearance: [],
    position: null,
    track_count: null,
    source: { provider, name, descriptions, text },
  };
}

function applyFormatEntry(block, entry, item) {
  if (entry.container) block.container = entry.container;
  if (entry.flag) block.flags.push(entry.flag);
  if (!entry.family && !entry.medium) return null;
  if (entry.medium) item.medium = entry.medium;
  if (entry.family) item.family = entry.family;
  if (entry.variant) item.variants.push(entry.variant);
  return item;
}

function finishItem(item, lookup) {
  if (item.medium && !item.family) item.family = lookup.media.get(item.medium).family;
  if (!item.medium) {
    const family = lookup.families.get(item.family);
    const resolved = family.resolve ? family.resolve.map[String(item[family.resolve.attribute])] : undefined;
    item.medium = resolved ?? `${item.family}_unspecified`;
  }
  const defaults = lookup.media.get(item.medium).defaults;
  for (const [attribute, value] of Object.entries(defaults)) if (item[attribute] === null) item[attribute] = value;
  item.variants = sortedUnique(item.variants);
  item.appearance = sortedUnique(item.appearance);
  return item;
}

function finishBlock(block) {
  block.families = sortedUnique(block.items.map((item) => item.family));
  for (const key of ["traits", "edition", "flags"]) block[key] = sortedUnique(block[key]);
  block.unmapped.formats = sortedUnique(block.unmapped.formats);
  block.unmapped.descriptions = sortedUnique(block.unmapped.descriptions);
  return block;
}

export function flattenDescriptions(descriptions) {
  if (descriptions === undefined || descriptions === null) return [];
  if (Array.isArray(descriptions)) return descriptions.filter((value) => typeof value === "string");
  if (typeof descriptions === "string") return [descriptions];
  if (typeof descriptions === "object" && "description" in descriptions) return flattenDescriptions(descriptions.description);
  return [];
}

function parseQty(value) {
  const qty = Number.parseInt(String(value ?? "1"), 10);
  return Number.isInteger(qty) && qty >= 1 ? qty : 1;
}

export function mapDiscogsFormats(taxonomy, formats) {
  const lookup = index(taxonomy);
  const block = emptyBlock(taxonomy);
  for (const format of Array.isArray(formats) ? formats : []) {
    if (format === null || typeof format !== "object") continue;
    const name = typeof format.name === "string" ? format.name : null;
    const descriptions = flattenDescriptions(format.descriptions);
    const text = typeof format.text === "string" ? format.text : null;
    const entry = name === null ? undefined : taxonomy.discogs.formats[name];
    let item = null;
    if (entry === undefined) {
      if (name !== null) block.unmapped.formats.push(name);
    } else {
      item = applyFormatEntry(block, entry, newItem("discogs", name, descriptions, text));
      if (item) item.qty = parseQty(format.qty);
    }
    for (const description of descriptions) {
      const rule = taxonomy.discogs.descriptions[description];
      if (rule === undefined) {
        block.unmapped.descriptions.push(description);
        continue;
      }
      const { target, value } = rule;
      if (target === "ignore") continue;
      if (ITEM_ATTRIBUTES.has(target)) {
        if (item && item[target] === null) item[target] = value;
      } else if (target in ITEM_LISTS) {
        if (item) item[ITEM_LISTS[target]].push(value);
      } else if (target in RELEASE_LISTS) {
        block[RELEASE_LISTS[target]].push(value);
      } else if (target === "release_kind" || target === "packaging" || target === "container") {
        if (block[target] === null) block[target] = value;
      }
    }
    if (item) block.items.push(finishItem(item, lookup));
  }
  return finishBlock(block);
}

export function mapMusicBrainzRelease(taxonomy, release) {
  const lookup = index(taxonomy);
  const block = emptyBlock(taxonomy);
  const media = Array.isArray(release?.media) ? release.media : [];
  for (const medium of media) {
    if (medium === null || typeof medium !== "object") continue;
    const name = typeof medium.format === "string" && medium.format !== "" ? medium.format : null;
    const item = newItem("musicbrainz", name, [], null);
    item.position = Number.isInteger(medium.position) ? medium.position : null;
    item.track_count = Number.isInteger(medium.track_count) ? medium.track_count : null;
    if (name === null) {
      item.medium = "other_unspecified";
    } else {
      const entry = taxonomy.musicbrainz.formats[name];
      if (entry === undefined) {
        block.unmapped.formats.push(name);
        continue;
      }
      if (applyFormatEntry(block, entry, item) === null) continue;
    }
    block.items.push(finishItem(item, lookup));
  }
  const status = release?.status;
  if (typeof status === "string") {
    const edition = taxonomy.musicbrainz.status[status];
    if (edition === undefined) block.unmapped.descriptions.push(status);
    else if (edition !== null) block.edition.push(edition);
  }
  const packaging = release?.packaging;
  if (typeof packaging === "string") {
    const mapped = taxonomy.musicbrainz.packaging[packaging];
    if (mapped === undefined) block.unmapped.descriptions.push(packaging);
    else block.packaging = mapped;
  }
  const group = release?.release_group ?? {};
  if (typeof group.primary_type === "string") {
    const kind = taxonomy.musicbrainz.primary_types[group.primary_type];
    if (kind === undefined) block.unmapped.descriptions.push(group.primary_type);
    else block.release_kind = kind;
  }
  for (const secondary of Array.isArray(group.secondary_types) ? group.secondary_types : []) {
    if (typeof secondary !== "string") continue;
    const trait = taxonomy.musicbrainz.secondary_types[secondary];
    if (trait === undefined) block.unmapped.descriptions.push(secondary);
    else block.traits.push(trait);
  }
  return finishBlock(block);
}

export function mapFixtureInput(taxonomy, fixture) {
  if (fixture.provider === "discogs") return mapDiscogsFormats(taxonomy, fixture.input.formats);
  if (fixture.provider === "musicbrainz") return mapMusicBrainzRelease(taxonomy, fixture.input);
  throw new Error(`unknown fixture provider: ${fixture.provider}`);
}

export function validateTaxonomy(taxonomy) {
  const errors = [];
  const familyIds = new Set(taxonomy.families.map((family) => family.id));
  const mediumIds = new Set(taxonomy.media.map((medium) => medium.id));
  const values = taxonomy.values;
  const targetSets = {
    channels: new Set(values.channels),
    codec: new Set(values.codecs),
    variant: new Set(values.variants),
    appearance: new Set(values.appearances),
    release_kind: new Set(values.release_kinds),
    trait: new Set(values.traits),
    edition: new Set(values.editions),
    packaging: new Set(values.packagings),
    container: new Set(values.containers),
    flag: new Set(values.flags),
  };
  for (const family of taxonomy.families) {
    if (!mediumIds.has(`${family.id}_unspecified`)) errors.push(`family ${family.id} needs a ${family.id}_unspecified medium`);
    for (const target of Object.values(family.resolve?.map ?? {})) {
      if (!mediumIds.has(target)) errors.push(`family ${family.id} resolves to unknown medium ${target}`);
    }
  }
  for (const medium of taxonomy.media) {
    if (!familyIds.has(medium.family)) errors.push(`medium ${medium.id} has unknown family ${medium.family}`);
    if (!medium.id.startsWith(`${medium.family.split("_")[0]}_`)) errors.push(`medium ${medium.id} must be prefixed by its family`);
  }
  const checkFormatEntry = (provider, name, entry) => {
    if (entry.family && !familyIds.has(entry.family)) errors.push(`${provider} format ${name} has unknown family ${entry.family}`);
    if (entry.medium && !mediumIds.has(entry.medium)) errors.push(`${provider} format ${name} has unknown medium ${entry.medium}`);
    if (entry.variant && !targetSets.variant.has(entry.variant)) errors.push(`${provider} format ${name} has unknown variant ${entry.variant}`);
    if (entry.container && !targetSets.container.has(entry.container)) errors.push(`${provider} format ${name} has unknown container ${entry.container}`);
    if (entry.flag && !targetSets.flag.has(entry.flag)) errors.push(`${provider} format ${name} has unknown flag ${entry.flag}`);
    if (entry.variant && !entry.medium) errors.push(`${provider} format ${name} sets a variant without a medium`);
    if ((entry.container || entry.flag) && (entry.medium || entry.family)) errors.push(`${provider} format ${name} mixes a release fact with a medium`);
  };
  for (const [name, entry] of Object.entries(taxonomy.discogs.formats)) checkFormatEntry("discogs", name, entry);
  for (const [name, entry] of Object.entries(taxonomy.musicbrainz.formats)) checkFormatEntry("musicbrainz", name, entry);
  for (const [name, rule] of Object.entries(taxonomy.discogs.descriptions)) {
    if (rule.target === "ignore") {
      if ("value" in rule) errors.push(`discogs description ${name} ignores but carries a value`);
    } else if (rule.target === "size_inches" || rule.target === "speed_rpm") {
      if (typeof rule.value !== "number" || rule.value <= 0) errors.push(`discogs description ${name} needs a positive numeric value`);
    } else if (!targetSets[rule.target]?.has(rule.value)) {
      errors.push(`discogs description ${name} has value ${rule.value} outside the ${rule.target} set`);
    }
  }
  for (const value of Object.values(taxonomy.musicbrainz.status)) if (value !== null && !targetSets.edition.has(value)) errors.push(`musicbrainz status maps to unknown edition ${value}`);
  for (const value of Object.values(taxonomy.musicbrainz.packaging)) if (!targetSets.packaging.has(value)) errors.push(`musicbrainz packaging maps to unknown packaging ${value}`);
  for (const value of Object.values(taxonomy.musicbrainz.primary_types)) if (!targetSets.release_kind.has(value)) errors.push(`musicbrainz primary type maps to unknown release kind ${value}`);
  for (const value of Object.values(taxonomy.musicbrainz.secondary_types)) if (!targetSets.trait.has(value)) errors.push(`musicbrainz secondary type maps to unknown trait ${value}`);
  for (const [group, list] of Object.entries(values)) {
    if (JSON.stringify(list) !== JSON.stringify(sortedUnique(list))) errors.push(`values.${group} must be sorted and unique`);
  }
  for (const [provider, section] of [["discogs", taxonomy.discogs.formats], ["discogs", taxonomy.discogs.descriptions], ["musicbrainz", taxonomy.musicbrainz.formats]]) {
    const keys = Object.keys(section);
    if (JSON.stringify(keys) !== JSON.stringify(sortedUnique(keys))) errors.push(`${provider} mapping keys must be sorted`);
  }
  return errors;
}
