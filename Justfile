# SPDX-License-Identifier: MIT

set shell := ["bash", "-euo", "pipefail", "-c"]
tool := "mise exec --"

default:
    @just --list

# Install the exact repository toolchain.
setup:
    mise install

# Run the complete credential-free local and CI boundary.
check: syntax-check test policy-check links catalog taxonomy brand license-check audit secret-scan build install-check

syntax-check:
    {{tool}} node --check brand/render.mjs
    {{tool}} node --check scripts/build.mjs
    {{tool}} node --check scripts/check-governance.mjs
    {{tool}} node --check scripts/media-mapper.mjs
    {{tool}} node --check scripts/validate.mjs
    {{tool}} node --check scripts/validate.test.mjs
    bash -n scripts/check-secrets.sh

test:
    {{tool}} node --test scripts/validate.test.mjs

coverage:
    mkdir -p coverage
    {{tool}} node --test --experimental-test-coverage --test-reporter=lcov --test-reporter-destination=coverage/lcov.info scripts/validate.test.mjs

policy-check:
    {{tool}} node scripts/check-governance.mjs
    {{tool}} node scripts/validate.mjs --policy

links:
    {{tool}} node scripts/validate.mjs --links

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

build:
    {{tool}} node scripts/build.mjs

install-check: build
    {{tool}} node scripts/build.mjs --check

# Run the complete review gate, then emit the exact immutable handoff for infra.
publication-readiness:
    just check
    {{tool}} node scripts/publication-readiness.mjs
