# Prototype integration readiness and release evidence

**Status, checked 2026-11-08:** bounded offline prototype work is underway on existing owners. This record reserves future integration capacity and records published evidence; it does not file the successor integration specifications or approve serving or deployment.

## Coordination checkpoint

The existing API integration owner acknowledged that the then-current producer work had no branch collisions and had an exact release cut. This records that technical acknowledgement only; future edits to reserved paths require fresh coordination.

All eight core children are reviewed and merged into the catalog-api prototype epic. The producer-side contracts and routes for these prototypes have not been promoted. The OpsLedger surface is already present on operations-console main at `71b74e807581ad2c00434231ad0f89361cac4e4c`.

## Published main and contract revisions

| Repository | Published main or release | Contract evidence |
| --- | --- | --- |
| `catalog-api` | main and `v0.11.1` peel to `c04b540b8c005612505be99f3b614e0f90e04d3a`; annotated tag object `b778b2d960a06fcc7e15275532cf0cd3523fb283` | At the released API revision, [`contracts/persistence/v1/source.json`](https://github.com/groovemap-music/catalog-api/blob/c04b540b8c005612505be99f3b614e0f90e04d3a/contracts/persistence/v1/source.json) pins producer commit `8e1117f8fbf2d3ad419e30851494d6ee9978edf7` and compatibility SHA-256 `df59203d12b454a2c57fcc0f562c17062ed10ec8881d24aa3f45ce9c2f9e19f3`. |
| `database-schema` | main and `v0.12.0` peel to `df17cecead1ec8cfd83f103bb63e7ddb8d5db9b5`; annotated tag object `bd49044db7336e51d6c5a1d799eec07f5ff90b4f` | The latest published producer contract is [`contracts/persistence/v1/compatibility.json`](https://github.com/groovemap-music/database-schema/blob/df17cecead1ec8cfd83f103bb63e7ddb8d5db9b5/contracts/persistence/v1/compatibility.json). It is newer than the schema revision pinned by the released API; adopting added persistence behavior requires consumer-owned promotion. |
| `graph-explorer` | main `8c4cec5b1e3dbffa02d9961be6ccb41762ccc095` | [`contracts/catalog-api/graph-explorer/v1/source.json`](https://github.com/groovemap-music/graph-explorer/blob/8c4cec5b1e3dbffa02d9961be6ccb41762ccc095/contracts/catalog-api/graph-explorer/v1/source.json) pins producer commit `334fca36e13dc277db3aeb16242aa777605d4966` and contract SHA-256 `ab8f205e0c7513d73c6aafede4903be0e4ff6cf9353b9f012645b94f1ddaf86b`. |
| `operations-console` | main `71b74e807581ad2c00434231ad0f89361cac4e4c` | OpsLedger is on main. [`contracts/catalog-api/operations-console/v1/source.json`](https://github.com/groovemap-music/operations-console/blob/71b74e807581ad2c00434231ad0f89361cac4e4c/contracts/catalog-api/operations-console/v1/source.json) pins producer commit `c31703b0f869d0631fa6b22beedd86cf5e950fd4` and contract SHA-256 `5bb3cad3cc98b985534c8001f967dfdef66cf0e2d08300e2fb52fc5a02d2ec4e`. |

These consumer pins are valid for the behavior they currently use. A newer database or API revision does not require every consumer to upgrade; promote and pin a contract when a consumer adopts added behavior. These are source revisions and contract references, not evidence of a production deployment or an unrecorded runtime schema application. `database-schema` owners manage their own migration/backfill work. No vector-schema prerequisite is required for the initial offline cores.

The offline fixture evaluators run without a live database. GM10's owner-scoped copy reader uses existing datastore behavior and its current database surface; it adds no schema or new service. Its runtime-backed nature does not make the separate offline evaluators database-dependent.

`catalog-api/api/queries/search_queries.py` remains reserved by existing search work (`gm-catalog-api-4asm` and `gm-catalog-api-2jka`) until that work merges. Any later change to that path requires fresh coordination with its owner.

## Reserved integration slots

The dispatcher `disp/prototypes` retains sequence ownership. Reserve only these two future developer slots, one active task per slot at a time:

| Reserved seat | Scope when later filed | Start condition |
| --- | --- | --- |
| `dev/proto-contracts` | Wire approved API contract behavior in catalog-api and publish an immutable producer commit with contract tests and release evidence. | The producer behavior is reviewed; a stable source-owned contract is declared; any persistence change has a separately reviewed schema compatibility plan. |
| `dev/proto-shell` | Integrate prototype surfaces into the existing graph-explorer shared shell and promote its consumer contract pin. | The required catalog-api producer commit is immutable and published; graph-explorer has reviewed its source pin and tests against that exact revision. |

These names are reservations, not active claims, launch assignments, or permission to start the successor molecules. `catalog-api-integration.yaml` (two tasks) and `graph-explorer.yaml` (nine tasks) remain **unfiled**. They require a reviewed evidence GO, immutable producer-contract promotion, and separate serving approval. None is approved or running.

## Independent work and consumer waits

| Work | Can start independently? | Consumer dependency |
| --- | --- | --- |
| Offline evaluators and transient cores on catalog-api that use fixture inputs | Yes. No live database, schema vector, new runtime, or consumer service is required. Report fixture provenance and quality limits. | A passing offline evaluator alone does not create or promote a contract. |
| API behavior or route contract wiring | Only after the relevant feature's evidence and owner review; no consumer can infer a contract from a prototype module. | Publish and pin one immutable catalog-api producer commit before implementing consumers against it. |
| Graph Explorer shell and feature surfaces | Shared shell planning can proceed within the existing app boundary; feature reads/writes wait for their source contract. | Pin the exact published producer revision in graph-explorer and run consumer-owned contract/behavior tests before exposure. |
| Persistence changes | Not an initial offline-core prerequisite. | `database-schema` compatibility review, consumer promotion, and any required owner-run migration/backfill must be complete before a feature depends on new storage. |

## Per-feature promotion and exposure gates

| Prototype | Minimum gate before consumer promotion or feature exposure |
| --- | --- |
| GM01 — catalog, owner, and operator evidence | Keep public release facts, selected-copy owner evidence, and operator alias history on their separate authority and access paths. Operator calls require existing authentication and `require_admin` authorization. |
| GM05 — Ask evaluation | Review offline evaluator results before changing Ask behavior; synthetic or incomplete labels do not establish real answer quality. |
| GM06 — Missing scope preview | Keep it transient with explicit known denominator and needs-review evidence. Saved pursuit requires separate persistence, export, consent, retention, and erasure design. |
| GM07 — Discover replay | Do not expose ranking changes until replay evidence and any consented historical-input requirements are reviewed. Do not infer new impressions or outcomes. |
| GM08 — crate comparison | Preserve the user-selected bounded candidate set and declared joint-coverage unit/denominator; no catalog-wide candidate production. |
| GM10 — copy observations | Select a specific owner-authorized copy; preserve copy-scoped histories. Correction, retraction, or supersession semantics remain a separate gate. |
| GM12 — run-out interpretation | Keep source spans and unknown/ambiguous attribution visible. Real reviewed corpus quality remains **PENDING**; no alias normalization or writes. |
| GM13 — known release comparison | Compare only explicitly user-selected known releases. Keep ties and contradictions inspectable; no catalog-wide candidate generation or identity promotion. |

## Release boundary

Prototype merge, immutable contract promotion, consumer promotion, feature exposure, and production deployment are separate decisions. This record authorizes none of the latter three. A future release record must name the exact producer and consumer revisions and their successful checks; an offline result or a schema release by itself is not deployment evidence.
