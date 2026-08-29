# GrooveMap design

This repository owns GrooveMap's canonical brand sources, generated brand assets, public architecture decisions, and sanitized repository catalog. The editable design tokens and SVG templates live in [`brand/`](brand/); applications and documentation consume the generated assets rather than maintaining independent copies.

The [`catalog/repositories.json`](catalog/repositories.json) catalog describes the public responsibilities and relationships of all 20 organization repositories. Its deliberately narrow schema excludes provider identifiers, access policy, secret distribution, source-extraction paths, and other operational configuration. Public architecture decisions are indexed in [`docs/`](docs/README.md).

## Licensing and identity

Repository software, documentation, and design source are available under the [MIT License](LICENSE). Each contributor retains copyright in their contribution unless they separately agree otherwise.

The MIT License is a copyright license. It does not grant permission to imply that another product, service, organization, or event is an official GrooveMap offering or is sponsored or endorsed by GrooveMap. See [TRADEMARKS.md](TRADEMARKS.md) for permitted referential and community use of GrooveMap names and logos, and [NOTICE](NOTICE) for the concise rights boundary.

## Contributing

Public contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes. Brand-source changes must include the corresponding deterministic generated assets and pass `just check`.

The [brand guide](brand/README.md) documents the source layout, asset reproduction, and font-provenance requirements.

## Validation and automation

Install the pinned tools with `just setup`, then run the credential-free `just check` gate. It verifies local links, the public catalog through a pinned standards-compliant JSON Schema 2020-12 implementation, the immutable CI caller, license metadata, public-content safety, full-history secret scans, deterministic rendering, the reviewed 12-asset checksum set, and a deterministic package containing the assets and applicable notices.

Pull requests and pushes to `main` use the reusable GrooveMap CI workflow pinned to an immutable automation commit. Dependabot opens ordinary pull requests, so dependency updates execute the same required job and complete validation graph as contributor pull requests; there is no actor-specific reduced path.

The catalog schema is available at [`catalog/repositories.schema.json`](catalog/repositories.schema.json). Its contract is exercised with synthetic data in [`fixtures/catalog-valid.json`](fixtures/catalog-valid.json) and against the canonical catalog. Private operational metadata remains outside this repository.
