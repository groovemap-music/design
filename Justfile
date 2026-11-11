# SPDX-License-Identifier: MIT

set shell := ["bash", "-euo", "pipefail", "-c"]
tool := "mise exec --"

default:
    @just --list

# Install the exact repository toolchain.
setup:
    mise install

# Run the complete credential-free local and CI boundary.
check: lint test policy-check links catalog taxonomy identity events identifiers company-roles brand license-check audit secret-scan build install-check

# Statically validate executable source and the repository recipe contract.
lint:
    {{tool}} node --check brand/font.mjs
    {{tool}} node --check brand/mark.mjs
    {{tool}} node --check brand/render.mjs
    {{tool}} node --check scripts/brand-font.test.mjs
    {{tool}} node --check scripts/brand-tokens.mjs
    {{tool}} node --check scripts/brand-tokens.test.mjs
    {{tool}} node --check scripts/build.mjs
    {{tool}} node --check scripts/check-governance.mjs
    {{tool}} node --check scripts/check-recipes.mjs
    {{tool}} node --check scripts/check-recipes.test.mjs
    {{tool}} node --check scripts/genre-tree.mjs
    {{tool}} node --check scripts/genre-tree.test.mjs
    {{tool}} node --check scripts/mb-tag-drift.mjs
    {{tool}} node --check scripts/mb-tag-drift.test.mjs
    {{tool}} node --check scripts/mb-tag-genre.mjs
    {{tool}} node --check scripts/mb-tag-genre.test.mjs
    {{tool}} node --check scripts/mb-tag-review.mjs
    {{tool}} node --check scripts/mb-tag-review.test.mjs
    {{tool}} node --check taxonomy/mb-tag-genre/review/core.js
    {{tool}} node --check scripts/media-mapper.mjs
    {{tool}} node --check scripts/publication-readiness.mjs
    {{tool}} node --check scripts/tooling.mjs
    {{tool}} node --check scripts/validate.mjs
    {{tool}} node --check scripts/validate.test.mjs
    {{tool}} node --check scripts/validation-policy.mjs
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

# Serve the mb-tag-genre review page on localhost (no network calls; Ctrl-C stops it), or open it as a file.
tag-review:
    @echo "Review page: http://127.0.0.1:8765/index.html  (Ctrl-C to stop; the page also works from file://)"
    {{tool}} python3 -I -m http.server 8765 --bind 127.0.0.1 --directory taxonomy/mb-tag-genre/review

# Rebuild the review page's data from the lookup (run after a merge).
tag-review-build:
    {{tool}} node scripts/mb-tag-review.mjs build

# Offline drift check of the lookup against a newer vocabulary and/or tree; exits 1 on broken paths.
# just tag-drift --new-vocab new-vocab.json --new-tree new-tree.json --out drift.json --out-review review-work.json
tag-drift *flags:
    {{tool}} node scripts/mb-tag-drift.mjs --lookup taxonomy/mb-tag-genre/v1/mb-tag-genre.json --tree taxonomy/mb-tag-genre/v1/discogs-genre-tree.json {{flags}}

# Apply a review export to the lookup: just tag-review-merge ~/Downloads/mb-tag-genre-review-....json
tag-review-merge export *flags:
    {{tool}} node scripts/mb-tag-review.mjs merge --export {{export}} {{flags}}

# Validate the native identity vocabulary and its schema.
identity:
    {{tool}} node scripts/validate.mjs --identity

# Validate the first-party event vocabulary, both envelope schemas, and the conformance fixtures.
events:
    {{tool}} node scripts/validate.mjs --events

# Validate the catalog identifier vocabulary, both schemas, and the conformance fixtures.
identifiers:
    {{tool}} node scripts/validate.mjs --identifiers

# Validate the company-role vocabulary, both schemas, and the conformance fixtures.
company-roles:
    {{tool}} node scripts/validate.mjs --company-roles

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
