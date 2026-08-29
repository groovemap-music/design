# ADR 0003: AGPL and commercial licensing model

- Status: Accepted

## Context

GrooveMap is an open-source project. The analytics service, catalog API, graph explorer, and operations console should remain open source while offering a separate path for organizations that do not want to comply with network copyleft requirements.

## Decision

`analytics-engine`, `catalog-api`, `graph-explorer`, and `operations-console` are licensed under `AGPL-3.0-only`. Their complete corresponding source must be offered as required by that license when modified versions are made available for interaction over a network.

A separate commercial license may be offered for these four repositories. The commercial option is an alternative grant from the relevant copyright holders; it does not remove, narrow, or make the AGPL grant conditional for recipients who comply with the AGPL.

Other intended-public repositories use MIT unless their repository states a different reviewed license. The private planning archive grants no public license. Trademark permission remains separate from every copyright license.

## Consequences

Community users have an Open Source Initiative-recognized path to use, study, modify, and share the software. Commercial users who need terms incompatible with the AGPL can request a separate license. Contributions must preserve a rights chain that allows both the AGPL distribution and any separately agreed commercial licensing.
