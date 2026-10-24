# Harness for spike gm-design-6b8u

This is throwaway code for
[Concept D's ledger bar on real months](../gm-design-6b8u-strata-ledger-months.md). It is
not a product package, and no GrooveMap service depends on it. Its outputs in `results/`
are aggregates only: counts, months, and rates. The full export and the JSON dumps are
streamed and never written to disk. Their compact extracts stay under
`~/.cache/groovemap-spikes/gm-design-6b8u/` and `~/.cache/groovemap-spikes/gm-design-loj9/`,
outside the repository.

## Provenance

Copied from gm-design-loj9 (merged at `3fdb051` on `wt/bead/epic/gm-design-uq8t`), not
imported:

- `scripts/extract_mb.py` and `scripts/stream_mb.sh`: the `musicbrainz-ingestion`
  Discogs-id rule and the JSON-dump stream. The only change is the work directory.
- `scripts/guard.py`: the aggregate-only guard from loj9's `scripts/measure.py`.
- `tests/conftest.py`.

The JSON-dump extracts (`mb_release_*`, `mb_release-group_20261021-001001`) and the Discogs
extracts (`discogs_releases_20260901`, `discogs_masters_20261001`) are read from loj9's
work directory. loj9's README gives their reproduce commands.

## Files

| File | Role |
| --- | --- |
| `scripts/extract_mb_history.py`, `scripts/stream_mb_history.sh` | Stream the full export's `mbdump.tar.bz2` (`core`) or `mbdump-derived.tar.bz2` (`derived`). `core` writes each Discogs release link's release id, row id, Discogs id, `last_updated`, release MBID, and release-group MBID, plus every release-URL row's id and `last_updated`. `derived` writes `release_meta.date_added` |
| `scripts/months.py` | Proxy 1 and proxy 2 link times, validation against the exact JSON diff, the monthly model, and G1-G3. Writes `results/months.json` |
| `scripts/oos.py` | Proxy 2's binding out-of-sample validation (20261021 → 20261024). Writes `results/oos_validation.json` |
| `results/oos_validation.json` | Its result: precision 0.912, recall 0.9771 (passes) |
| `sql/predecessor_schema.sql` | Read-only schema and content check of the predecessor catalog's four link-structure tables (correction 2 in the spike document) |
| `tests/` | Synthetic fixtures only: the calendar, both directions of validation error, the monthly model, G2, the creation bound, the extractor on a tiny invented `mbdump`, and the privacy guard |

## Reproducing

```bash
cd docs/spikes/gm-design-6b8u
export UV_PROJECT_ENVIRONMENT=~/.cache/groovemap-spikes/gm-design-6b8u/.venv
uv sync
uv run pytest
export PY=$UV_PROJECT_ENVIRONMENT/bin/python

# The full export: about 11 minutes for core and 1 minute for derived. Nothing is cached.
scripts/stream_mb_history.sh 20261021-002201 derived
scripts/stream_mb_history.sh 20261021-002201 core

# Validation and months (about 5 minutes, about 6 GB of memory).
(cd scripts && $PY months.py ~/.cache/groovemap-spikes/gm-design-loj9/data ~/.cache/groovemap-spikes/gm-design-6b8u/data \
   ~/.cache/groovemap-spikes/gm-design-loj9/data/discogs_releases_20260901.tsv.gz ../results/months.json)
```

### The binding out-of-sample validation (run 2026-10-24: passed)

```bash
# After 2026-10-24: the full export dated 20261024 (check its exact name in the index),
# and the JSON release member 20261024-001001.
scripts/stream_mb_history.sh 20261024-102842 derived
scripts/stream_mb_history.sh 20261024-102842 core
W=~/.cache/groovemap-spikes/gm-design-6b8u scripts/stream_mb.sh 20261024-001001 release
cp ~/.cache/groovemap-spikes/gm-design-loj9/data/mb_release_20261021-001001.tsv.gz ~/.cache/groovemap-spikes/gm-design-6b8u/data/
(cd scripts && $PY oos.py ~/.cache/groovemap-spikes/gm-design-6b8u/data ~/.cache/groovemap-spikes/gm-design-6b8u/data \
   ../results/oos_validation.json)
```

### The predecessor schema check

The check is read-only, and the maintainer approved it. Host, container, role, and database
are withheld.

```bash
{ echo "BEGIN TRANSACTION READ ONLY; SET LOCAL statement_timeout = '300s';"; cat sql/predecessor_schema.sql; echo "COMMIT;"; } \
  | ssh -o BatchMode=yes <host> docker exec -i <container> psql -X -q -A -t -U <role> -d <database>
```
