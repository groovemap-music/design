# ADR 0019: Placement and evidence boundaries for metadata and collection prototypes

- Status: Accepted for bounded offline prototypes on 2026-11-08; production exposure and rollout remain separately gated

## Context

Eight GrooveMap-only prototypes are approved for implementation and offline evaluation on existing
product boundaries. The work must preserve the current ownership of catalog facts, user evidence,
identity, persistence, and consumer contracts. This record carries only the public architecture
needed to place that work; it does not reproduce planning material or grant production launch
approval.

The relevant existing boundaries are [ADR 0001](0001-repository-ownership-boundary.md): each product
repository owns its source and release, `database-schema` owns persistence contracts, and
`design` owns public architecture; [ADR 0005](0005-source-owned-catalog-ingestion.md): source
producers own their event contracts; [ADR 0009](0009-native-identity-and-provider-aliases.md):
catalog identity and user-owned copies/observations have distinct authorities; [ADR 0010](0010-first-party-events-consent-and-deletion.md): activity is consented and erasable; [ADR 0011](0011-catalog-identifiers-and-manufacturing-credits.md): release identifiers retain provider
evidence and exact alias rules; [ADR 0014](0014-cross-catalog-edition-candidates.md): production
candidate generation is gated; [ADR 0016](0016-strata-graph-view.md): Strata uses current
collector state and keeps personal layers out of shareable views; and [ADR 0018](0018-operations-console-single-shell.md): OpsLedger sits inside the authenticated operations
shell.

## Decision

### Existing owners and surfaces

| Prototype | Owner and existing runtime | Product surface and bounded behavior |
| --- | --- | --- |
| **GM01 — three evidence views** | `catalog-api` owns catalog reads, owner-scoped observations, and admin identity-history reads. `graph-explorer` owns user-facing views; `operations-console` owns OpsLedger. | Public release fact drawer shows catalog-sourced release and credit facts. Collection copy detail shows private owner evidence about the selected copy. OpsLedger shows read-only alias and supersession history to authorized operators through the existing `require_admin` boundary. These are separate facts, audiences, and access paths. |
| **GM05 — Ask evaluation** | `catalog-api` owns the existing NLQ behavior and its offline evaluator; `graph-explorer` owns Ask. | Evaluate the existing behavior offline before changing Ask. Evaluation fixtures and reports are not production answers, user feedback, or a new runtime. |
| **GM06 — missing-scope preview** | `catalog-api` owns the pure scope/counting core and any API behavior; `graph-explorer` owns the existing Missing pane and later Collection UI. | Show missing scope as a transient preview in Missing, with a later entry point in Collection. The preview is not saved pursuit state and does not write collection membership. |
| **GM07 — Discover replay** | `catalog-api` owns the first offline replay/ranking evaluator by extending its existing `api/evaluation` harness; `graph-explorer` owns Discover. | Replay a bounded fixture or consented historical input without changing the live ranking path or creating impressions/outcomes. Any future activity writes still follow ADR 0010. A scheduled or global computation belongs in `analytics-engine` only if later evidence justifies it. |
| **GM08 — crate comparison** | `catalog-api` owns the existing Fit computation/API; `graph-explorer` owns Will it fit?. | Compare bounded, user-selected candidate sets by marginal joint coverage against the collector's existing context. Each evaluation declares its coverage unit and denominator, and reports the delta from the current collection. This is not catalog-wide coverage or a new recommendation feed. |
| **GM10 — copy observations** | `catalog-api` owns authenticated observation GET/POST behavior; `database-schema` owns the persistence contract; `graph-explorer` owns the UI. | Collection copy detail and Strata's explicit copy selection can read or record observations for that selected owned copy. Selection does not change catalog facts or collector state. |
| **GM12 — run-out interpretation** | `catalog-api` owns the pure parser and offline fixture evaluator; `graph-explorer` owns release detail presentation. | Read the existing release `identifiers`/matrix value and show source spans with supported, ambiguous, or unknown attribution. A separate owner observation remains copy-level evidence. Parsing does not normalize identifiers or write aliases. |
| **GM13 — selected release comparison** | `graph-explorer` owns Search, release detail, and Fit picker surfaces; `catalog-api` owns any eventual comparison API and its producer contract. | Compare only known catalog releases the user explicitly selects, in Search, the release drawer, or Fit picker. This is contextual comparison, not catalog-wide candidate production or identity promotion. |

Catalog facts remain grounded in source-owned ingestion and the catalog projections that consume
those contracts. A user's observation is evidence about that user's selected copy, not a correction
to a release or a new identity assertion. Alias validity and supersession history remain governed
by ADR 0009; the UI is a read-only view of that authority.

### Matching and identity remain separate

ADR 0014 section 6 remains **DEFER** for production release-edition candidate generation until its
stated unlinked-population measurement clears the recorded bar. Nothing in these prototypes creates
a catalog-wide candidate job, candidate store, review queue, or identity promotion path. GM13's
comparison set comes only from known catalog releases selected by the user. GM12's parser consumes
supplied evidence and leaves ADR 0011 alias normalization unchanged. Neither prototype writes to
`provider_aliases` or upgrades a candidate to identity.

### Contract ownership and runtime boundary

These prototypes use the existing `catalog-api`, `graph-explorer`, and `operations-console`
boundaries. This decision adds no service, deployment unit, persistence table,
runtime dependency, or shared source import. `design` owns this public decision; source ingestion
contracts remain with their producers under ADR 0005; `catalog-api` owns its API contract;
`database-schema` owns persistence contracts; and each consumer promotes the producer contract it
uses in its own repository.

Any future API surface must be added through the existing versioned producer and consumer contract
process. An event change requires the appropriate ADR 0010 and event-contract review. A persistence
change belongs to `database-schema` and its compatibility contract. No endpoint, event, schema, or
exposure change is approved merely by this placement decision.

## Separate gates

- **Prototype implementation:** may proceed within the owners and surfaces above, using offline
  evaluators and synthetic or reviewed fixtures appropriate to each task. Evaluator results must
  state what data they use and must not be presented as production-quality evidence when they are
  synthetic or incomplete.
- **Production exposure and rollout:** requires a separate reviewed implementation plan and the
  normal owner-repository release/deployment gates. This ADR is not a launch approval.
- **Saved pursuit:** persistence, export, consent, retention, and erasure for a saved comparison or
  scope require a separate design decision consistent with ADR 0010 before any durable state is
  added.
- **Observation correction:** edit, retraction, correction, and supersession semantics for recorded
  observations require a separate decision before writes can alter or replace existing evidence.
- **Schema or contract changes:** require review by the existing producer/consumer owners and
  `database-schema` when persistence changes; no schema change is part of this ADR.

## Consequences

The prototypes can be built and evaluated without creating another runtime or blurring catalog,
owner, and operator evidence. The boundaries also make later product exposure explicit work: a
passing offline evaluator alone does not authorize durable user state, identity changes, a public
endpoint, or deployment.
