# Result 05 — Effect of query-aware scalar retention

**Arms:** same binary, one env flag. `HEADROOM_QUERY_AWARE_SCALARS` off vs on.
**Cells:** 250 per arm (175 needle + 75 control) · **API cost:** $0 · **Runtime:** ~190 s per arm
**Data:** [`data/v2_off.csv`](data/v2_off.csv) · [`data/v2_on.csv`](data/v2_on.csv)
**Compare:** [`repro/qcr_compare.py`](repro/qcr_compare.py)

## Headline

| Position stratum | Cells | Baseline | Query-aware | Delta |
|---|---:|---:|---:|---:|
| head (guaranteed) | 50 | 100.0% | 100.0% | +0.0pp |
| **interior** | **100** | **28.0%** | **100.0%** | **+72.0pp** |
| tail (guaranteed) | 25 | 100.0% | 100.0% | +0.0pp |
| all needle cells | 175 | 58.9% | **100.0%** | +41.1pp |

Interior retention by array size — the regime where baseline collapses:

| N | Baseline | Query-aware | Delta |
|---:|---:|---:|---:|
| 20 | 50.0% | 100.0% | +50.0pp |
| 60 | 25.0% | 100.0% | +75.0pp |
| 150 | 20.0% | 100.0% | +80.0pp |
| 400 | 20.0% | 100.0% | +80.0pp |
| 1000 | 25.0% | 100.0% | +75.0pp |

## Token cost went **down**

```
forwarded bytes   off=248,110   on=237,409   delta = -10,701  (-4.31%)
items retained    off=3,996     on=3,158     delta = -838
```

The improvement is not bought with tokens. Pinned items are drawn **from within** the existing K
budget, so stride-fill shrinks to compensate; the result is better retention at slightly lower cost.

## Controls show no regression

The three control questions are ones where relevance is the *wrong* criterion — this is the guard
against a tautological result.

| Question | Cells | Baseline kept | Query-aware kept | Baseline head-10 | Query-aware head-10 |
|---|---:|---:|---:|---:|---:|
| `count` ("how many items?") | 25 | 15.8 | 15.9 | 4.8 | 5.0 |
| `first` ("list the first ten") | 25 | 15.8 | 15.8 | 4.8 | 4.8 |
| `spread` ("describe the distribution") | 25 | 15.8 | 15.8 | 4.8 | 4.8 |

Representative sampling is preserved. The diversity floor caps relevance at 30% of the K budget
(`HEADROOM_QUERY_AWARE_FRACTION`, default 0.3), so summary questions keep their spread.

## Two implementation errors found along the way, both by measurement

**1. Wrong scorer.** The crusher's default is `HybridScorer`. On opaque identifiers its embedding
half assigns every item an identical score, so ranking collapsed to index order and the pins landed
on the head — which was already guaranteed — while stealing stride slots from the target. Retention
went *down*, 28% → 22%. Probe ([`tests/scorer_probe.rs`](../crates/headroom-core/tests/scorer_probe.rs)):

```
HYBRID  target_score=0.5000  max=0.5000  rank=44   above_0.3=200
BM25    target_score=0.2079  max=0.2079  rank=1    above_0.3=0
```

Fixed by scoring scalar arrays with BM25 explicitly. Short opaque IDs are exactly where lexical
IDF is strongest and semantic similarity is meaningless.

**2. Wrong "no signal" test.** The original guard was `max <= 0.0`. The real degenerate signature is
**zero spread** — Hybrid's uniform 0.5 has a high value and no information. Also, BM25 scores over
short documents are small in absolute terms (a rank-1 exact match scored 0.208), so the config's
absolute `relevance_threshold` of 0.3 rejected perfect matches. Both replaced with relative tests:
pin at `>= 0.5 x batch_max`, defer entirely when `max - min <= 1e-6`.

## Threats to validity

- **Synthetic arrays.** Whether real agent traffic produces flat scalar arrays at all is still
  unmeasured. This is the outstanding kill criterion in [PROPOSAL.md](PROPOSAL.md).
- **Needle queries quote the identifier verbatim.** [result-01](result-01-bm25-scalar-feasibility.md)
  shows BM25 contributes *nothing* when the query only describes the item semantically. The 100%
  applies to the quoting case; the fallback is measured to be safe, not equally effective.
- **The controls are coarse.** They check retained-count and head-coverage, not whether a model
  answers summary questions correctly. That needs the LLM layer.
- **No live agent yet.** These are proxy-level measurements, not task outcomes.

## Test status

| Scope | Result |
|---|---|
| `smart_crusher` unit tests (Rust) | **329 passed, 0 failed** |
| `headroom-core --lib` overall | 260+ passed, **0 failed**, 8 hanging |
| Hanging tests | `transforms::detection::*` — magika/ONNX model init |

The 8 hanging tests were verified as **pre-existing**: with the change stashed (`git stash`), the
same 8 tests hang identically on unmodified code (`exit 124`). They exercise content-type detection,
a different module from the modified selection path, and appear to block on ML model download in
this environment.
