# SPDX-License-Identifier: MIT

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Run repository governance and deterministic-output checks.
check:
    node scripts/check-governance.mjs
    node brand/render.mjs --check

# Verify that tracked brand assets match their canonical sources.
brand:
    node brand/render.mjs --check

# Regenerate brand assets after changing canonical sources.
brand-render:
    node brand/render.mjs
