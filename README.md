# GrooveMap design

This repository owns GrooveMap's canonical brand sources, generated brand assets, public architecture decisions, and sanitized repository catalog. The editable design tokens and SVG templates live in [`brand/`](brand/); applications and documentation consume the generated assets rather than maintaining independent copies.

The [`catalog/repositories.json`](catalog/repositories.json) catalog describes the public responsibilities and relationships of all 21 organization repositories: 19 public repositories plus the private `infra` and `planning-archive` boundaries. Its deliberately narrow schema excludes provider identifiers, access policy, secret distribution, source-extraction paths, and other operational configuration. Public architecture decisions are indexed in [`docs/`](docs/README.md). The [`taxonomy/media/`](taxonomy/media/README.md) directory owns the canonical media vocabulary, its schemas, and the conformance fixtures that every service vendors under [ADR 0007](docs/adr/0007-canonical-media-taxonomy.md). The [`taxonomy/identity/`](taxonomy/identity/README.md) directory owns the native identity vocabulary under [ADR 0009](docs/adr/0009-native-identity-and-provider-aliases.md), and [`taxonomy/events/`](taxonomy/events/README.md) owns the first-party event vocabulary, its two envelope schemas, and their conformance fixtures under [ADR 0010](docs/adr/0010-first-party-events-consent-and-deletion.md). [`taxonomy/identifiers/`](taxonomy/identifiers/README.md) and [`taxonomy/company-roles/`](taxonomy/company-roles/README.md) own the catalog identifier types and the company-role categories, their block schemas, and their conformance fixtures under [ADR 0011](docs/adr/0011-catalog-identifiers-and-manufacturing-credits.md).

Organization-level ownership is deliberately split: `.github` owns the public profile and
community-health files, `automation` owns reusable workflows, this repository owns public
design contracts, `infra` applies private operational policy, and `planning-archive`
preserves historical planning rather than acting as an active decision source.

## Licensing and identity

Repository software, documentation, and design source are available under the [MIT License](LICENSE). Each contributor retains copyright in their contribution unless they separately agree otherwise.

The MIT License is a copyright license. It does not grant permission to imply that another product, service, organization, or event is an official GrooveMap offering or is sponsored or endorsed by GrooveMap. See [TRADEMARKS.md](TRADEMARKS.md) for permitted referential and community use of GrooveMap names and logos, and [NOTICE](NOTICE) for the concise rights boundary.

## Contributing

Public contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes. Brand-source changes must include the corresponding deterministic generated assets and pass `just check`.

The [brand guide](brand/README.md) documents the source layout, asset reproduction, and font-provenance requirements.

## Validation and automation

Install the pinned tools with `just setup`, then run the credential-free `just check` gate. It verifies local links, the public catalog and the media, identity, event, identifier, and company-role vocabularies through a pinned standards-compliant JSON Schema 2020-12 implementation, the immutable CI caller, license metadata, public-content safety, full-history secret scans, deterministic rendering, the reviewed 12-asset checksum set, and a deterministic package containing the assets and applicable notices.

Pull requests and pushes to `main` use the reusable GrooveMap CI workflow pinned to an immutable automation commit. Dependabot opens ordinary pull requests, so dependency updates execute the same required job and complete validation graph as contributor pull requests; there is no actor-specific reduced path.

The catalog schema is available at [`catalog/repositories.schema.json`](catalog/repositories.schema.json). Its contract is exercised with synthetic data in [`fixtures/catalog-valid.json`](fixtures/catalog-valid.json) and against the canonical catalog. Private operational metadata remains outside this repository.

Repository-specific recipes keep design capabilities visible instead of hiding them behind generic automation names:

| Recipe | Purpose |
| --- | --- |
| `policy-check` | Validate public governance, the local recipe-provider contract, immutable CI, and exposure boundaries. |
| `links` | Verify repository-local Markdown references without contacting remote services. |
| `catalog` | Validate the canonical public repository catalog and its closed schema. |
| `taxonomy` | Validate the canonical media vocabulary, schemas, mapper, and conformance fixtures. |
| `identity` | Validate the native identity vocabulary and its schema. |
| `events` | Validate the first-party event vocabulary, both envelope schemas, and the conformance fixtures. |
| `identifiers` | Validate the catalog identifier vocabulary, its block schema, and the conformance fixtures. |
| `company-roles` | Validate the company-role vocabulary, its block schema, and the conformance fixtures. |
| `brand` | Prove generated assets match canonical sources and the reviewed checksum manifest. |
| `brand-render` | Regenerate brand assets explicitly after canonical source changes. |
| `publication-readiness` | Repeat the full gate and emit an immutable, non-publishing handoff for separately approved infrastructure work. |

The generic `lint`, `test`, `coverage`, `audit`, `license-check`, `secret-scan`, `build`, and `install-check` recipes implement the shared automation capabilities. `brand-render` remains an explicit source-generation command and `publication-readiness` never publishes, tags, changes visibility, or modifies organization settings.

## Publication handoff

The current 19-public/2-private visibility state is established. From a clean review commit,
`just publication-readiness` repeats the complete gate and emits the exact Design commit,
catalog digest, and taxonomy digest that infrastructure can pin for a future reviewed
promotion. It does not publish or change visibility. See [PUBLICATION.md](PUBLICATION.md) for
the handoff contract.
