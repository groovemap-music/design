# Publication readiness

GrooveMap's current publication state is 19 public repositories plus the private `infra`
and `planning-archive` boundaries. Visibility remains a separately reviewed infrastructure
concern. This repository's review process prepares immutable evidence for future catalog,
taxonomy, or brand promotions; it does not change visibility, publish a release, or mutate
organization settings.

Run the handoff from a clean reviewed commit:

```console
just publication-readiness
```

The command first runs the complete credential-free `just check` gate. That gate verifies local links, the canonical 21-repository catalog and its closed schema, public-content safety, deterministic brand rendering, byte identity of reviewed assets, licensing, packaging, and both worktree and full-history secret scans. It then prints a JSON handoff containing:

- the exact design commit;
- the SHA-256 of `catalog/repositories.json`;
- the SHA-256 and version of `taxonomy/media/v1/media-taxonomy.json`;
- the SHA-256 and version of `taxonomy/identity/v1/identity-vocabulary.json` and `taxonomy/events/v1/event-types.json`;
- the SHA-256 and version of `taxonomy/identifiers/v1/identifier-types.json` and `taxonomy/company-roles/v1/company-roles.json`;
- the catalog repository count and schema version;
- the sorted source-owned ingestion repository identities; and
- an explicit statement that no publication action was performed.

Infrastructure may pin those values after its own review without copying private operational
configuration into this repository. A later reviewer can regenerate the handoff from the
same commit and compare it byte-for-byte before authorizing any downstream promotion. The
handoff is provenance, not permission to modify a consumer or its visibility.
