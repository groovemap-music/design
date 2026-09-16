# Public architecture decisions

These records describe stable, public boundaries for the GrooveMap organization. They explain ownership and contribution expectations without carrying credentials, provider identifiers, access policy, deployment values, or unpublished planning details.

Accepted records remain historical evidence. When implementation changes or clarifies an
accepted boundary, the record retains its original decision and adds a dated amendment or
an explicit supersession. The repository catalog and program status documents describe the
maintained current state.

- [ADR 0001: Repository ownership boundary](adr/0001-repository-ownership-boundary.md)
- [ADR 0002: Shared automation boundary](adr/0002-shared-automation-boundary.md)
- [ADR 0003: AGPL and commercial licensing model](adr/0003-agpl-commercial-licensing.md)
- [ADR 0004: Beadhive-compatible branch policy](adr/0004-beadhive-compatible-branch-policy.md)
- [ADR 0005: Source-owned catalog ingestion repositories](adr/0005-source-owned-catalog-ingestion.md)
- [ADR 0006: OpenTelemetry metrics and Grafana dashboards](adr/0006-opentelemetry-metrics.md)
- [ADR 0007: Canonical media taxonomy and media-neutral product core](adr/0007-canonical-media-taxonomy.md)
- [ADR 0008: VictoriaMetrics backend, distributed tracing, runtime metrics, and alerting](adr/0008-victoriametrics-tracing-runtime-alerting.md)
- [ADR 0009: Native identity and provider aliases](adr/0009-native-identity-and-provider-aliases.md)
- [ADR 0010: First-party events, consent, and deletion closure](adr/0010-first-party-events-consent-and-deletion.md)
- [ADR 0011: Catalog identifiers, manufacturing credits, and release country](adr/0011-catalog-identifiers-and-manufacturing-credits.md)
- [ADR 0012: PostgreSQL SQL/PGQ as the catalog graph engine](adr/0012-postgresql-property-graph-migration.md)

## Program rollout plans

- [Media-taxonomy program rollout](programs/media-taxonomy.md) records the completed delivery of ADR 0007 across the organization in five waves.
- [Native identity and first-party events program rollout](programs/native-identity-and-events.md) records the four-wave delivery plan for ADR 0009 and ADR 0010, the artifacts each wave pins, and the gaps it deliberately leaves to their own records.
- [Catalog-identifiers program rollout](programs/catalog-identifiers.md) records the five-wave delivery plan for ADR 0011, the artifacts each wave pins, and the gaps it deliberately leaves to their own records.

## Design spikes

- [Shared delivery and batch-processing contract](spikes/gm-design-erl.1-delivery-contract.md)
  records the bounded GO decision for a shared settlement policy and a Discogs-only batch engine.

## Verification reports

- [Repowise defect-risk refresh — 2026-09-14](audits/repowise-defect-risk-2026-09-14.md)
  records the current exact-revision health, complexity, clone, dead-code, churn, coverage,
  hotspot, and current-HEAD risk evidence across the shared runtime, catalog API, and four consumers.
- [Shared-delivery rollout verification — 2026-09-14](audits/shared-delivery-rollout-2026-09-14.md)
  records the exact shared-runtime and four-consumer trees, immutable pins, validation and image
  gates, delivery-model boundaries, and fix-one-fix-all ownership guidance.
- [Organization-wide verification — 2026-09-13](audits/organization-wide-verification-2026-09-13.md)
  records the final sanitized 21-repository maintenance matrix and diagram audit.
