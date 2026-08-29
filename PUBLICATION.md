# Publication readiness

Public visibility is a separate infrastructure change. This repository's review process prepares immutable evidence; it does not change visibility, publish a release, or mutate organization settings.

Run the handoff from a clean reviewed commit:

```console
just publication-readiness
```

The command first runs the complete credential-free `just check` gate. That gate verifies local links, the canonical 20-repository catalog and its closed schema, public-content safety, deterministic brand rendering, byte identity of reviewed assets, licensing, packaging, and both worktree and full-history secret scans. It then prints a JSON handoff containing:

- the exact design commit;
- the SHA-256 of `catalog/repositories.json`;
- the catalog repository count and schema version; and
- an explicit statement that no publication action was performed.

Infrastructure must pin those values without copying private operational configuration into this repository. A later reviewer can regenerate the handoff from the same commit and compare it byte-for-byte before authorizing any visibility change.
