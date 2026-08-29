# ADR 0001: Repository ownership boundary

- Status: Accepted

## Context

GrooveMap is organized as independently testable and releasable repositories. Contributors need a public map of responsibilities without exposing operational configuration or historical planning material.

## Decision

Each product repository owns its source, tests, package or image definition, service-specific documentation, and release process. `database-schema` owns runnable persistence initialization and schema compatibility. `deployment` composes immutable releases and owns stack-level configuration, rollout, and rollback. `python-libraries` owns shared Python runtime and agent-tool packages. `automation` owns reusable continuous-integration, release, and security workflows. `design` owns brand sources, public architecture decisions, and the sanitized repository catalog.

The `infra` repository remains the private infrastructure-as-code and operational-policy boundary. `planning-archive` remains the private historical-planning boundary. Neither repository is a source for runtime imports.

Cross-repository contracts are versioned or pinned at consumption boundaries. A consumer must not reach into another repository through a filesystem-relative import.

## Consequences

Repository READMEs can describe one clear responsibility. Release artifacts have a single owner, and public metadata can stay useful without reproducing access rules, secrets, environment values, or private planning state.
