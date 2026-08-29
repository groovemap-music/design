# ADR 0002: Shared automation boundary

- Status: Accepted

## Context

Independent repositories need consistent pull-request validation and release evidence while preserving each repository's own build and test contract.

## Decision

`automation` publishes reusable GitHub Actions workflows and composite actions. Callers pin every external workflow or action to a full commit revision. Each repository retains a credential-free `just check` entry point and passes its repository-specific setup, test, audit, license, secret-scan, build, and install commands into the shared workflow.

Dependabot pull requests use the same required caller job and complete validation graph as contributor pull requests. Workflows must not reduce coverage based on the actor. Shared automation receives only the minimum permissions and explicitly declared inputs or secrets required by a job; broad secret inheritance is not part of the contract.

Release workflows produce immutable artifacts, checksums, software bills of materials, third-party notices, and provenance appropriate to the release unit. Deployment consumes immutable image digests rather than mutable tags.

## Consequences

Policy is consistent without centralizing repository-specific build logic. A workflow revision is reviewable as an ordinary source dependency, and automated dependency updates exercise the same gates as all other changes.
