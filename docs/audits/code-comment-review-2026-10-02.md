# Code comment review — 2026-10-02

Reviewed the executable maintenance comments against design source revision
`a73912e97b7b988ee0501322934243fe13c04e1a` for `gm-design-5uc`. The previous
bead notes reported 19 extracted comments and a no-change review; this review
rechecked the live source rather than relying on that conclusion.

## Accuracy correction

The comment above `isPlainEntry` in `scripts/media-mapper.mjs` described a
“plain object”. The predicate tests only `typeof value === "object"`, non-null,
and non-array. It does not check the prototype, so class instances also satisfy
it. The comment now describes that exact shape guard and its prototype limit.
The predicate and every mapper result remain unchanged.

## Retained comments

| Source | Review evidence and disposition |
| --- | --- |
| SPDX headers in executable scripts and `Justfile` | MIT provenance; retained. The shell shebang remains an execution directive. |
| `scripts/media-mapper.mjs` reference-mapper header | ADR 0007 and taxonomy conformance fixtures define the cross-language output contract; retained. |
| `scripts/media-mapper.mjs` own-property lookup explanation | `Object.hasOwn` prevents upstream names such as `constructor` from resolving inherited members. Existing prototype-name conformance coverage exercises that boundary; retained. |
| `scripts/validation-policy.mjs` version-1 noun exception | The `nouns_of_record` branch intentionally permits record names without past-tense verbs; retained. |
| `scripts/validation-policy.mjs` ADR 0011 mapper header | Identifier and company fixture validators compare mapper outputs with canonical expected blocks; retained as compatibility rationale. |
| `scripts/validation-policy.mjs` own-property lookup explanation | `ownGet` uses `Object.hasOwn` for untrusted upstream identifier names; retained. |
| `scripts/validation-policy.mjs` MusicBrainz field explanation | The mapper reads scalar `barcode` and each `label-info[].catalog-number`, preserving unrecognised fields in `unmapped`; retained. |
| `Justfile` recipe comments | Checked against their command bodies: pinned setup, local verification, canonical brand rendering, dependency policy, build/install, and publication evidence; retained. |
| Workflow references | External actions remain pinned to full commit revisions. No version annotations, tooling directives, or provenance were removed. |

No ADR policy, executable statements, canonical taxonomy, brand inputs, generated
assets, workflow revisions, or dependencies changed. Validation uses the existing
complete `just check` gate; this comment audit does not require new behaviour tests.
