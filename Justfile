# SPDX-License-Identifier: MIT

set shell := ["bash", "-euo", "pipefail", "-c"]
tool := "mise exec --"

default:
    @just --list

# Install the exact repository toolchain.
setup:
    mise install

# Run the complete credential-free local and CI boundary.
check: lint test policy-check links catalog taxonomy brand license-check audit secret-scan build install-check

# Statically validate executable source and the repository recipe contract.
lint:
    {{tool}} node --check brand/render.mjs
    {{tool}} node --check scripts/build.mjs
    {{tool}} node --check scripts/check-governance.mjs
    {{tool}} node --check scripts/check-recipes.mjs
    {{tool}} node --check scripts/check-recipes.test.mjs
    {{tool}} node --check scripts/media-mapper.mjs
    {{tool}} node --check scripts/validate.mjs
    {{tool}} node --check scripts/validate.test.mjs
    bash -n scripts/check-secrets.sh

test:
    {{tool}} node --test scripts/*.test.mjs

coverage:
    mkdir -p coverage
    {{tool}} node --test --experimental-test-coverage --test-reporter=lcov --test-reporter-destination=coverage/lcov.info scripts/*.test.mjs

# Validate public repository policy and this repository's automation-provider contract.
policy-check:
    {{tool}} node scripts/check-governance.mjs
    {{tool}} node scripts/check-recipes.mjs
    {{tool}} node scripts/validate.mjs --policy

# Verify local Markdown references without contacting remote services.
links:
    {{tool}} node scripts/validate.mjs --links

# Validate the public repository catalog and its closed schema.
catalog:
    {{tool}} node scripts/validate.mjs --catalog

# Validate the canonical media taxonomy, its schemas, and the conformance fixtures.
taxonomy:
    {{tool}} node scripts/validate.mjs --taxonomy

# Verify that tracked brand assets match their canonical sources.
brand:
    {{tool}} node brand/render.mjs --check
    {{tool}} node scripts/validate.mjs --assets

# Regenerate brand assets after changing canonical sources.
brand-render:
    {{tool}} node brand/render.mjs

license-check:
    {{tool}} node scripts/validate.mjs --license

# The repository has no package-manager dependencies; fail if that changes without an audit policy.
audit:
    {{tool}} node scripts/validate.mjs --dependencies

secret-scan:
    @{{tool}} scripts/check-secrets.sh

# Build the deterministic, locally consumable design artifact.
build:
    {{tool}} node scripts/build.mjs

# Verify the built artifact exactly matches its canonical inputs.
install-check: build
    {{tool}} node scripts/build.mjs --check

# Run the complete review gate, then emit the exact immutable handoff for infra.
publication-readiness:
    just check
    {{tool}} node scripts/publication-readiness.mjs
