# Result 02 — What Headroom's own benchmark suite actually measures

Source: [`headroom/evals/suite_runner.py`](../headroom/evals/suite_runner.py),
[`runners/before_after.py`](../headroom/evals/runners/before_after.py)

## Tier 1 suite

| Benchmark | Category | Runner | Samples |
|---|---|---|---|
| GSM8K | reasoning | lm_eval | 100 |
| TruthfulQA | factual | lm_eval | 100 |
| MMLU | knowledge | lm_eval | ~114 |
| ARC-Challenge | science | lm_eval | 100 |
| HumanEval | code | lm_eval | 164 |
| SQuAD v2 | qa | before_after | 100 |
| BFCL | tool_use | before_after | 100 |
| **Tool Outputs** | **agent** | before_after | **8** |
| CCR Round-trip | lossless | compression_only | — |

Default model throughout: **`gpt-4o-mini`** (`suite_runner.py:41`).

## What this tells us

### 1. It is a *safety* suite, not an *efficacy* suite

`BeforeAfterRunner`'s own docstring states the design:

> 1. Run query with ORIGINAL context → Response A
> 2. Run query with COMPRESSED context → Response B
> 3. Compare A and B … Report if accuracy is preserved
> This is the gold standard for proving compression doesn't break anything.

The primary metric is `accuracy_preservation_rate`. The question being asked is
**"does compression hurt?"**, not **"does compression help, and where does it fail?"**
That is a legitimate and well-built regression suite. It is simply not an efficacy measurement.

### 2. The agent regime is barely covered

GSM8K, MMLU, ARC and TruthfulQA are single-turn, small-context tasks. Headroom's crushers require
`min_tokens_to_crush=200` and `min_items_to_analyze=5`, so on prompts of that size the compressors
largely no-op — the benchmarks confirm no damage on inputs that are mostly not compressed.

The one benchmark in the **agent** category, "Tool Outputs", has **`sample_size=8`**.

### 3. Nothing in the suite is multi-turn

Every Tier 1 entry is a single request/response pair. This is a direct structural explanation for
why [finding-02](finding-02-multiturn-compression-stops.md) (compression fires once per
conversation, then stops) would never be caught by the project's own testing: the defect only
appears on turn 2 and later, and the suite never reaches turn 2.

## Consequences for our evaluation

**Reuse, don't rebuild.** `BeforeAfterRunner` is already exactly the Phase B design — original vs.
compressed, `temperature=0.0` for reproducibility, semantic-similarity and ground-truth metrics.
The right move is to add a **dataset** and a **retention arm**, not to build a parallel harness.
This keeps our numbers directly comparable to the project's published figures and reuses the
maintainers' own definition of "accuracy preserved".

**Keep `gpt-4o-mini`.** It is their default across every entry point, so results sit on the same
baseline rather than an incomparable one.

**The gap we fill is stated precisely.** Not "their benchmarks are bad" — they are a sound
accuracy-preservation suite. The gap is that **no benchmark measures whether the retained items are
the right ones**, which is exactly what [improvement-01](improvement-01-query-aware-retention.md)
changes and what [result-01](result-01-bm25-scalar-feasibility.md) shows is currently left to chance.
