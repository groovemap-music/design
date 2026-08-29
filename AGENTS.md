# Repository instructions

- Keep `just check` deterministic, credential-free, and free of live service access.
- Treat `brand/tokens.json` and `brand/templates/` as canonical; commit regenerated assets with source changes.
- Preserve the public catalog schema's allowlist. Operational values and private planning material do not belong here.
- Pin every external `uses:` reference to a full 40-character commit revision.
- Keep fixtures synthetic and document third-party design provenance before adding an asset or font.
- Do not publish, tag, change visibility, or modify organization settings from repository checks.
- Run `just check` before submitting work.
