# ADR 0020: MusicBrainz tag to Discogs genre and style lookup (mb-tag-genre/v1)

- Status: Accepted, 2026-11-10

## Context

MusicBrainz tags are the largest body of genre evidence GrooveMap ingests, and today they are
not mapped to the Discogs genre and style tree at all. The tag vocabulary is very large and
uneven: 220,592 distinct tags are used on artists, labels, releases and release groups, and
9,240,290 of their uses are positive net votes. The head is short and the tail is long. The
top 1,000 tags carry 86.5% of uses, and the last 4% of uses is spread over more than 100,000
tags. Most distinct tags past the head are not genres. They are places, artist and label names,
personal tags, formats and moods, so a lookup cannot be a whole-vocabulary genre guess.

A spike measured the options on public dumps and a labelled 200-tag sample. The spike's
findings are in
[`docs/tag-mapping-spike.md`](https://github.com/groovemap-music/musicbrainz-graph-enricher/blob/ee3efa8a764d180b73ea2dec85fa3d4af08d72d1/docs/tag-mapping-spike.md)
in `musicbrainz-graph-enricher` at commit `ee3efa8a764d180b73ea2dec85fa3d4af08d72d1`, which is
the source of truth for every figure in this record. The spike harness is throwaway code. No
production path calls a model, and no projection or schema code was added.

Two constraints from the product set the shape of the answer:

- **No LLM is a source of catalog truth.** Ingest and the enricher read a lookup. They never
  classify a tag themselves, and no model's output reaches the catalog unreviewed.
- **A wrong genre is worse than no genre.** A wrong genre puts a release in the wrong place in
  the genre tree. A wrong NONE only leaves a tag unmapped, which is the current state.

The spike found that normalized string matching is precise but misses most genre-like tags, and
that model-based classification is accurate enough to propose genres for review, but that the
models' own confidence cannot be trusted to accept them.

## Decision

The GrooveMap design for MusicBrainz tags is a **reviewed, versioned lookup** built offline.
It is named `mb-tag-genre/v1` and lives under `taxonomy/mb-tag-genre/v1/`, next to the
existing `taxonomy/media/` and `taxonomy/company-roles/` vocabularies (see [ADR 0007](0007-canonical-media-taxonomy.md) and
[ADR 0011](0011-catalog-identifiers-and-manufacturing-credits.md) for the pattern). Each row
holds the tag, its result (`NONE`, a genre, or a genre and style path), the method that produced
it, the source dump date, the model IDs, both model proposals, and the reviewer. The lookup
ships with a JSON Schema and conformance fixtures.

### Source and scope

- **MusicBrainz:** v1 is built from **one named MusicBrainz dump**, chosen when the generator
  runs and recorded in the lookup with its SHA-256 checked against `SHA256SUMS`. The spike used
  the `mbdump-derived.tar.bz2` of full export `20261101-125824`; that export is the measured
  example, not a fixed source. A *use* is one (entity, tag) row with a positive net vote count,
  read from the `tag`, `artist_tag`, `label_tag`, `release_tag` and `release_group_tag` tables.
  These are the four entity types whose tags MusicBrainz ingestion keeps.
- **Discogs tree:** v1 is built from **releases plus masters of one named Discogs dump**, streamed.
  The spike built its tree from the masters dump `discogs_20261101_masters.xml.gz` alone
  (2,608,936 masters) and did not stream the releases dump. `gm-design-d7xz` re-measured it from
  releases plus masters of dump 20261101 (19,575,942 releases and 2,608,936 masters); the frozen
  tree is [`taxonomy/mb-tag-genre/v1/discogs-genre-tree.json`](../../taxonomy/mb-tag-genre/v1/discogs-genre-tree.json).
- **v1 scope:** tags with **20 or more uses**. In the spike's example dump that is **9,880 tags**,
  which carry about 95% of tag uses. The count is re-measured on the dump the generator uses.
  Tags with 5 to 19 uses are excluded from v1 (see *Future work*).

### Discogs tree

The tree is frozen from a named dump with the share rule that `insights.style_parents` already
applies (parents at share >= 0.20 of a style's masters, the rule the Atlas spike measured). The
dominant parent of each style is always kept. The v1 tree, built from releases plus masters of
dump 20261101, has **15 genres, 757 styles and 1,234 parent pairs**. 352 styles have two or more
parents, and no genre has more than 240 children, under TypeSafe's 255-option Choice limit. The
spike's masters-only tree, kept here only as the comparison, had 15 genres, 756 styles and 1,276
parent pairs, and at most 248 children per genre. The alternatives below were measured on that
masters-only tree.

Two alternatives were measured and rejected as trees. Observed co-occurrence gives 8,886 pairs,
and 685 of 756 styles then have six or more parent genres. The `graph.part_of` rule (masters
with exactly one genre) gives 3,162 pairs, and 213 styles still have six or more parents.

A style with several genres is kept as separate full paths, such as `Electronic/Trip Hop` and
`Hip Hop/Trip Hop`. The root has a NONE option, and every genre has a genre-only option.

### Order of precedence

1. **Normalized string match** against the Discogs style and genre names. A match is accepted
   **without review**. In the sample it made no wrong assignment: 43 of 43 assignments were right.
2. **Otherwise, two model proposals:** Jev beam K=3 and flat Claude each propose a result for
   the tag.
3. **Both say NONE:** the tag stays unmapped. It is not reviewed and no row is written as a
   genre.
4. **They agree on a genre or style, or they disagree:** a person reviews the tag. Claude's
   answer is the default suggestion, because when the models disagree Claude is right more
   often.

### Review rule

- **Every model-proposed genre is reviewed by a person.** No model proposal reaches the lookup
  unreviewed, whether the models agree or not.
- **Unreviewed model rows never ship.** A row that carries a model proposal and has no named
  reviewer is not published in any version of the lookup.
- **Both-NONE tags are unmapped.** They are recorded as NONE with both model proposals. They
  are not reviewed, and they do not appear as genres.

### Model dependency

- Models are used **only in an offline batch**, never during ingest, enrichment or serving.
  The enricher and ingest do a plain lookup.
- Model IDs are **pinned and versioned**, never an alias. The v1 pins are `jev-1.14.0` (TypeSafe
  Jev beam K=3 plus greedy) and `claude-opus-5-5` (effort medium). The spike's cookbook names
  `jev-1.12`, but the provider lists only `jev-1.14.0` and `jev-1.13.0`, so the harness pins
  `jev-1.14.0` and aborts if a response reports another model.
- Model responses are **captured and committed** with the lookup. A rerun from the committed
  captures makes no network calls and is reproducible. Cache misses are the only paid calls,
  and they happen only when the generator is run with live access on purpose.

### Versioning

A new `vN` is cut when the Discogs tree or the tag vocabulary drifts. The tree is frozen from a
named dump, so a changed tree is a new version rather than an edit in place. Existing versions
stay available for consumers that pin them.

### Drift check

`scripts/mb-tag-drift.mjs` diffs the lookup with a newer vocabulary (tags with 20 or more uses) and
a newer tree. It reports new tags, tags that fell out of scope, tree paths that no longer exist,
and use-count changes as a summary. It lists new tags and broken paths as review work and exits
non-zero on broken paths. It runs offline, makes no model calls and never runs the generator.

CI runs the structural part (lookup against its own tree, schemas, review-state invariants) in
`just check` on every change. The dump-based part is a documented command, run when a new dump or
tree is adopted. The command is in the [README](../../taxonomy/mb-tag-genre/README.md#drift-check).

Cut `v2` when the drift check finds a broken path, when the tree dump changes, when new tags
exceed about 10% of the lookup's tags, or when `min_uses` or a model pin changes. A smaller
tag-only change on the same tree and dump is a patch of the current version.

## Evidence

All figures are from the spike document at `ee3efa8a764d180b73ea2dec85fa3d4af08d72d1`. Accuracy
is graded against the **operator-reviewed answer key**, which the operator reviewed in full on
2026-11-10. The earlier draft key favoured the models, so its figures are not used here.

**Accuracy on the 200-tag labelled sample** (`exact` means the predicted path is one the key
accepts; `genre-like` means tags whose key has no NONE answer, 123 tags):

| Method | Exact | Genre-like exact | Junk to NONE | When it assigns, right |
| --- | --- | --- | --- | --- |
| String, normalized | 60.0% | 35.0% | 100% | 100% (43 of 43) |
| Jev beam K=3 | 85.5% | 80.5% | 94.7% | 90.8% (of 109) |
| Flat Claude (`claude-opus-5-5`, effort medium) | 92.0% | 88.6% | 97.3% | 96.5% (of 115) |

**Separation is not a usable signal.** Jev's separation score has an AUROC of **0.64** for right
against wrong answers, and it cannot set an auto-accept threshold. Raising the threshold barely
raises precision (85.5% with no threshold, 90.8% at 2.0, 92.9% at 5.0) while the review queue
grows to most of the vocabulary.

**Agreement is a usable signal.**

| Bucket | Sample tags | Right (Jev / Claude) | Est. tags >= 20 uses |
| --- | --- | --- | --- |
| String match assigns | 43 | 100% (string) | 1,172 |
| Both models name the same genre or style | 40 | **97.5%** / 97.5% | 1,987 |
| Both models say NONE | 80 | 87.5% / 87.5% | 4,546 |
| Models disagree | 37 | 64.9% / 86.5% | 2,174 |

When both models name the same genre or style, 39 of 40 sample answers are right. All 10 errors
in the both-NONE bucket are missed genres, not wrong ones. Leaving them unmapped is today's state.

**Review queue.** The review covers the agreed genre proposals and the disagreements,
about **4,200 tags** for the 20-or-more-uses vocabulary. The sample is 200 tags, so the
estimate carries a wide margin. `gm-design-uvs4` measured it on the v1 run (export
`20261111-002335`, 9,899 tags): **4,415** rows, 2,410 agreements and 2,005 disagreements.

**Cost and time.** Measured on the sample at list prices read 2026-11-01, extrapolated to the
9,880 tags with 20 or more uses: Jev is **$2.08** and about **0.6 h** sequentially, and flat
Claude is **about $53**. Together that is about $55 of model calls, once. Cost does not decide
between the two methods. Jev is a cheap independent second opinion, and agreement with it is what
makes Claude's proposals quick to review.

The v1 run (`gm-design-uvs4`, 2026-11-11) cost **$46.65** at the same list prices, from the token
counts in its committed captures: Jev $1.76 for 28,243 requests, and Claude $44.89 for 8,978
requests. It took 4,654 s wall time at 4 workers. The lookup and its captures are in
[`taxonomy/mb-tag-genre/`](../../taxonomy/mb-tag-genre/README.md).

## Alternatives considered

- **Auto-accept on model separation.** Rejected. The AUROC of 0.64 means a threshold either
  lets wrong genres through or sends most of the vocabulary to review.
- **Flat Claude alone.** Not chosen as the only proposer. Claude is more accurate, but without
  Jev there is no independent second answer, and agreement between the two is what keeps the
  review queue near 4,200 tags.
- **Co-occurrence or `part_of` as the tree.** Rejected. Both leave most styles under six or more
  genres (see *Discogs tree*).
- **Models at serving time, or in ingest.** Rejected by the constraint that no LLM is a source of
  catalog truth. Ingest does a plain lookup.
- **Shipping the tag-to-genre mapping without review.** Rejected. Even with string matches
  accepted without review, a wrong model genre puts a release in the wrong place in the tree.

## Consequences

- The generator, the reviewers and the consumers build to one written rule. Changing the rule
  means a new ADR or a new `vN`.
- The lookup depends on both TypeSafe and the Anthropic API, **but only in the offline batch**.
  Ingest and serving have no provider dependency.
- Review work is real: about 4,200 rows for v1, with Claude's answer as the default. The review
  pace sets how fast the lookup can grow.
- Tags with 5 to 19 uses stay unmapped in v1, which is about 2% of tag uses by the spike's
  estimate.

## Future work

- **5-19-use band.** Extending v1 to tags with 5 to 19 uses would add about 21,201 tags to the
  candidate set. The spike estimates that it roughly triples the review work for about 2% more
  uses. A later version can add it once the v1 review pace is known.
- The deterministic Discogs tree export, the generator, the review workflow, the enricher
  projection, and the drift-check script are separate work, each gated by its own
  record. This ADR records the rule they build to.
