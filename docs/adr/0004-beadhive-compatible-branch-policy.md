# ADR 0004: Beadhive-compatible branch policy

- Status: Accepted

## Context

GrooveMap uses Beadhive to turn reviewed work items into isolated, testable changes. Repository protection must support that lifecycle while ensuring the default branch remains an integration boundary.

## Decision

`main` is the protected integration branch. Normal changes begin from a filed bead and use Beadhive-managed issue, batch, epic, or workstream branches. A developer validates and submits a leaf or batch; a distinct review decision resolves its review gate before a serialized merge. Epic and workstream containers collect approved child changes and land as explicit non-fast-forward integration commits. Merge history is preserved rather than silently squashed at the integration boundary.

Required checks apply to every pull request, including automated dependency updates. Direct pushes, force pushes, branch deletion, and bypasses are not part of the normal contribution path. Repositories that cannot enforce a rule while private on the selected hosting plan retain the same policy in automation and activate provider-enforced protection as part of the reviewed public-visibility transition.

Emergency changes still require a filed record, validation, and review; urgency changes scheduling, not evidence requirements.

## Consequences

The default branch remains auditable and green, Beadhive can preserve the relationship between decisions and commits, and public contributors follow the same review and validation path as maintainers and automation.
