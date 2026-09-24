# Harness for spike gm-design-chw.2

This is throwaway code for
[graph embeddings vs heuristics-2026-09](../gm-design-chw.2-graph-embeddings-vs-heuristics.md).
It is not a product package. The only committed outputs are the aggregate metrics in
`results/`. Dump extracts, subsets, and embeddings stay under `~/.cache/groovemap-spikes/`,
which is outside the repository.

## Files

| File | Role |
| --- | --- |
| `parse_dump.py` | Pass 1: stream-parses the gzip releases dump into integer arrays (ids, dates, media-family bits, and genre and style vocab ids) |
| `build_subset.py` | Pass 2: applies the time-split cut and draws the artist-seeded sample |
| `baseline_port.py` | Read-only copies of the catalog-api metric primitives and the heuristics-2026-09 similar-artist scorer |
| `catalog.py` | The sparse release graph, and the heuristic replayed on it (production path and dense all-artist form) |
| `check_golden.py` | Parity check: the port reproduces catalog-api's own output on the committed golden set |
| `embed.py` | FastRP (local) and Node2Vec (PyTorch Geometric) training, with time and RSS records |
| `evaluate.py` | Ground truth, exact cosine kNN, fusion, and every metric |
| `results/*.json` | Aggregate metrics and run records. They contain no ids, names, or vectors. |

## Reproducing

The runs use Python 3.14 with `uv`. The virtualenv lives outside the worktree so that the
repository secret scan never walks it.

```bash
export UV_PROJECT_ENVIRONMENT=~/.cache/groovemap-spikes/graphemb/venv
W=~/.cache/groovemap-spikes/graphemb/work
uv sync                                    # builds torch-cluster from source, about 2 minutes
uv run python check_golden.py /path/to/catalog-api
uv run python parse_dump.py ~/.cache/groovemap-spikes/dumps/discogs_20260901_releases.xml.gz $W/pass1
uv run python build_subset.py $W/pass1 $W/s10 --rate 0.10
uv run python embed.py $W/s10 $W/emb/frp128.npy --method fastrp --dim 128 --weights 0,1,1,1
uv run python embed.py $W/s10 $W/emb/n2v128.npy --method node2vec --dim 128
uv run python evaluate.py $W/s10 results/eval.json --emb frp128=$W/emb/frp128.npy --emb n2v128=$W/emb/n2v128.npy
```

Every process caps itself at 6 threads (`OMP_NUM_THREADS`, `torch.set_num_threads`).
`parse_dump.py` runs 5 parser workers plus the reader process.
