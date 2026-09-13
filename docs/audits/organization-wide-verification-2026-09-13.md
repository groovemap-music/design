# Organization-wide verification — 2026-09-13

Status: final review candidate

This report records the final sanitized verification after the organization-wide maintenance
remediations landed. The machine-readable, versioned source is
[`verification/organization-wide-v1.json`](../../verification/organization-wide-v1.json).
Repository revisions below are the exact reviewed inputs. Design was reviewed at
`1b9ab79ce8c2986262f35a7f04d89bf0629f3b5f`; the report addition deliberately does not invent a
self-referential Design commit. Its final tree is attested by the Beadhive check and submission
that gate this report.

## Verification method

- Every repository was clean at its recorded revision. Existing Beadhive validation evidence was
  matched by Git tree, not merely by branch name or commit ancestry; each recorded verdict was
  green. The Design input also passed `just check` before this report was added.
- Each maintained documentation surface was compared with `just --summary`. References to a
  different repository's recipe were classified as cross-repository contract examples rather
  than local commands. All documented local recipes resolve.
- Maintained relative links, anchors, and GrooveMap repository targets were resolved against the
  recorded trees. The final Design link check covers the links introduced by this report.
- Environment variables, public ports and endpoints, image names and immutable digests, queue
  names, schemas, event/API contracts, ownership links, and promoted-source provenance were
  compared with executable code, Compose/configuration, contract manifests, lock files, and
  repository-native policy tests.
- Fenced-block inspection found no maintained conceptual ASCII diagrams. All maintained
  conceptual diagrams are Mermaid.
- Mermaid source was extracted from the recorded Git trees. All 94 maintained blocks were
  parsed and rendered with `@mermaid-js/mermaid-cli@11.12.0` and Chrome Headless Shell
  `152.0.7977.75`, then checked against their adjacent prose and owning executable/configuration
  sources. Six additional blocks are preserved historical evidence and were counted but not
  rewritten or treated as maintained architecture. The resulting baseline is 94 maintained plus
  six excluded historical blocks, 100 total.

Private evidence is intentionally narrower. The `infra` and `planning-archive` rows reuse their
approved validation verdicts and disclose only repository identity, exact revision, and the
sanitized result. No private paths, values, topology, credentials, or archived content are copied
into this public report.

## Public repository matrix

`Tree` is the exact content tree that matched the green verdict. `Diagrams` counts maintained
Mermaid blocks. Evidence roots identify the source families used for the semantic contract review.

| Repository | Reviewed revision | Tree | Verdict | Diagrams | Evidence roots |
| --- | --- | --- | --- | ---: | --- |
| `.github` | `dc245aa4b237080b2db84eb1eec31b0f1cc1bd70` | `bb04bfa609892e0e622b178892eabf99094b225e` | Pass | 0 | `profile/`, `docs/`, `policy/`, workflows |
| `analytics-engine` | `e8d30627d5513a6e62b93e235ea979f9b0ae7edf` | `bd85575fcbb123456f615f2949d12ccb0440a418` | Pass | 2 | README, docs, contracts, runtime, recipes |
| `automation` | `cc0450350d4c9fe91561a900bb390edf1660b52f` | `e5bb3bb0adb8dd87423bc308400456e2230777ad` | Pass | 1 | README, interfaces, reusable workflows, composite actions |
| `catalog-api` | `3151db4a79eb5bb02d175f0204cd2f6c5acc7404` | `ca41381baf179da552879fd36d67399748aa227e` | Pass | 12 | README, docs, API configuration/runtime, contracts, recipes |
| `database-schema` | `58debe082f063e55ab8f8b00e0f3cb31bcd4de2a` | `4848d665fe25753f2ddcb2cda1e0bba899b2fa6c` | Pass | 2 | README, architecture, schema sources, persistence contracts, recipes |
| `deployment` | `0ea358a78a85372252f7c5c39dcf13b0a5214867` | `19b2eb9967e6c09c4c63cd0bca0a81c17286a6ad` | Pass | 11 | README, docs, Compose, configuration, image locks, recipes |
| `design` | `1b9ab79ce8c2986262f35a7f04d89bf0629f3b5f` | `053bcac37cc40d680077c9a3b60461231c381045` | Pass | 2 | catalog, ADRs, brand, taxonomy, recipes |
| `discogs-graph-enricher` | `906561a33282d598fffd490b7713d578e03e1bd5` | `87ade4409895b6e3c4489d2bb4126c7991ab4a24` | Pass | 7 | README, docs, promoted contracts, runtime, recipes |
| `discogs-ingestion` | `a3fe6c054ffc095f6ad5fd3235669c88f8fe1384` | `a061bd42ecfe33fa8b6ecffcdf8e95451fa706d9` | Pass | 8 | README, docs, event contract, runtime, recipes |
| `discogs-sql-loader` | `b85259dc432be46f16b32521f39a521cf851abd3` | `8765e19fe362a1623fee9afc600e8f690138a331` | Pass | 10 | README, docs, promoted contracts, runtime, recipes |
| `graph-explorer` | `6593ae4a9762f43f429611b4828007a74d1d59e7` | `1b460a28035c311bf3ec676d2e72ad1a8dadd6c0` | Pass | 4 | README, docs, API contract, browser/backend runtime, recipes |
| `groovemap-music.github.io` | `ad5ea5bdd4663bf2b72681defab8a5a66d0bd94f` | `78619365ce1697d35364adc57260f8fd09ef01aa` | Pass | 0 | README, site source, public assets, Pages workflow, recipes |
| `mcp-server` | `30afb452e924b4e02031651401850e81b7f6e061` | `2b462e9895a98d444e5c227fb4199ebdd6884bea` | Pass | 4 | README, docs, API contract, client-run transport, recipes |
| `musicbrainz-graph-enricher` | `d5026c448810f2b7c1ed1b1e276868e5abdbef96` | `d500387cd627f3fe489afebb77b5c5e290d4c93d` | Pass | 7 | README, docs, promoted contracts, runtime, recipes |
| `musicbrainz-ingestion` | `b98f1f86480dd4082ec99ab21f70e14500c6a666` | `792f5b7c8fedc334173411ab3d70a608f3a4fea1` | Pass | 6 | README, docs, event contract, runtime, recipes |
| `musicbrainz-sql-loader` | `0c301978800a8cc0de2d96ecd42b4374bf59aca7` | `0d77cbfe5212525178c5df0f70d391e43c16ecce` | Pass | 7 | README, docs, promoted contracts, runtime, recipes |
| `operations-console` | `e444ff4a5a58fd6ff5c662ea4d45be943a786a64` | `60192ca30a450ca7b3f573e6ecf0e19462de7179` | Pass | 2 | README, docs, promoted contracts, dashboard runtime, recipes |
| `operations-toolkit` | `b7b35b60409ba81e14ff95a1ef6ff1caafedb953` | `be36c2bca09ec86a3292c2e81cc59d03fe71545e` | Pass | 2 | README, docs, promoted contracts, utilities, recipes |
| `python-libraries` | `66b65dc322c7a6b742f7a84e55a598802ecb55f5` | `e5a1df488e4a03db064d7f21d5992c80ee6aa914` | Pass | 5 | README, docs, packages, tests, recipes |

## Private repository matrix

| Repository | Reviewed revision | Sanitized verdict |
| --- | --- | --- |
| `infra` | `cfc599ee44bfd30e1a63b429774b9b0c5e3aceab` | Pass |
| `planning-archive` | `764cde7a7b56ef882ce7d5fcae17a73bfe23b0ba` | Pass |

## Cross-repository conclusions

- `automation` is the only shared workflow and composite-action implementation owner; `.github`
  owns organization profile/community-health content, while infrastructure policy remains in its
  private owner.
- Design remains the public authority for repository catalog, architecture decisions, media
  taxonomy, and brand sources. Promoted assets and contracts retain immutable commit and digest
  provenance.
- Each ingestion repository owns its source-specific event contract. Graph and SQL consumers
  promote only the matching source contract; no active cross-source coordination remains.
- `database-schema` owns persistence contracts. Consumer provenance files resolve to the intended
  reviewed schema revisions: `91cbf6e3712a2fa403693b5c81fde729f29cb4ce` for the common
  persistence promotion and `8986d47a460fc8fc617de0daf62c9c3367dee715` for the
  MusicBrainz graph compatibility promotion.
- Deployment's digest-pinned Compose topology owns both ingestion services and the deployed
  applications it actually runs. `mcp-server` remains client-run and is not represented as a
  deployed Compose service.
- The current OpenTelemetry metric-export default is 60000 milliseconds unless the standard
  environment variable overrides it. ADR 0006 preserves its earlier 15000-millisecond text as
  explicitly historical rather than rewriting the accepted record.

No unresolved architecture, product, ownership, recipe, documentation, provenance, or diagram
discrepancy remained at the recorded input trees.
