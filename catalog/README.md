# Public repository catalog

[`repositories.json`](repositories.json) is the public, machine-readable map of GrooveMap's 20 repositories. It records what each repository is for, how repositories relate, what they release, their intended destination visibility, and their coarse publication state.

The catalog is intentionally not an infrastructure inventory. It excludes provider identifiers, access controls, team permissions, branch-rule identifiers, secret distribution, environment values, source-extraction paths, and unpublished planning state. Those values belong to private operational systems and must not be represented here, even as redacted placeholders.

[`repositories.schema.json`](repositories.schema.json) is the closed JSON Schema 2020-12 contract. `just catalog` validates the schema, the synthetic fixture, the canonical document, its exact repository set, relationship targets, sorting, and the public-field allowlist.
