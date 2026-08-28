# Improvement 01 — Query-aware retention for scalar arrays

**Type:** capability extension (not a bug fix) · **Status:** premise verified, not yet built
**Reproducible:** fully deterministic, no API key required for the primary metric

---

## The gap

Headroom extracts the user's question and threads it through the compression pipeline. It is used
to rank items in **dict** arrays. It is **silently dropped for scalar arrays** (strings, numbers).

Source-level evidence — `crates/headroom-core/src/transforms/smart_crusher/crushers.rs:113`:

```rust
pub fn crush_string_array(
    items: &[&str],
    config: &SmartCrusherConfig,
    bias: f64,          // <-- no query parameter exists
) -> (Vec<String>, String)
```

Selection is: adaptive K → error keywords → length anomalies → first/last boundary → **stride-fill
sampling**. Nothing consults the query.

Yet the machinery is all present and already wired:

| Component | Location | State |
|---|---|---|
| Query extraction | `handlers/anthropic.py:1662` `context=extract_user_query(...)` | active |
| Query parameter | `SmartCrusher.crush(content, query="", ...)` | accepted |
| BM25 / Embedding / Hybrid scorers | `headroom/relevance/` (`create_scorer()`) | implemented, unused on this path |
| Relevance ranking for dict arrays | documented in `docs/.../smart-crusher.mdx` | active |

## Premise verified empirically

`repro/query_independence.py` — 60 invoice IDs, four different questions:

```
asked about INV-2026-0021: survived=15  target_kept=True
asked about INV-2026-0044: survived=15  target_kept=False
asked about INV-2026-0009: survived=15  target_kept=False
asked about INV-2026-0055: survived=15  target_kept=False

kept set identical across all 4 different questions? True
kept: 0001 0002 0003 0004 0006 0011 0016 0021 0026 0031 0036 0041 0046 0059 0060
```

The retained set is **byte-identical regardless of what was asked**. The head/stride/tail pattern is
plainly visible. The one success was coincidence — `0021` happens to fall on the stride.

Baseline expected survival is therefore `K/N` — pure chance. At K=15, N=60 that is 25%, which is
exactly what was observed (1 of 4).

## The proposal

Route scalar arrays through the relevance scorer that already exists, at the **same token budget**:

- pass the extracted query into `crush_string_array` / `crush_number_array`,
- reserve part of the K budget for query-relevant items, scored with `create_scorer()` (BM25 default,
  zero new dependencies),
- keep the existing safety nets (error keywords, anomalies) additive and untouched,
- retain a diversity floor so the result is not 15 near-identical items,
- fall back to current behaviour verbatim when the query is empty or scores are flat.

Env-gated, default off, so the baseline arm is byte-identical to upstream.

## Benchmark design — "Query-Conditioned Retention"

**Primary metric is deterministic and needs no LLM**, which makes the headline result exactly
reproducible by a reviewer.

| Axis | Values |
|---|---|
| Array size N | 20, 60, 150, 400, 1000 |
| Target position p | swept across the array (head / stride-aligned / stride-gap / tail) |
| Content type | invoice IDs, file paths, log lines, test names, numeric IDs |
| Arm | baseline vs. query-aware |

Metrics:
1. **Retention rate** — does the queried item survive? (deterministic)
2. **Token cost** — tokens after compression (must not regress)
3. **Answer accuracy** — optional LLM layer: does the model answer correctly from the compressed
   context? (this is where the coding-agent/benchmark requirement of the task is satisfied)

Headline artifact: a **retention-vs-compression Pareto curve**, baseline against improved.

Expected: baseline ≈ K/N, improved ≈ 100%, at identical token budget.

## Threats to validity — to be addressed, not hidden

1. **The benchmark could be rigged for the mechanism.** Needle retrieval is precisely what relevance
   ranking optimises, so a win is close to tautological. The evaluation **must** include tasks where
   relevance is the wrong criterion — "how many items are there?", "what is the distribution of
   statuses?", "list the first ten" — and demonstrate no regression. Without that, the result is
   uninteresting.
2. **Vague or absent queries.** Many agent turns have no meaningful query. Must show graceful
   fallback, measured, not asserted.
3. **Diversity loss.** Relevance-only selection may return 15 near-identical items and lose the
   representative sample that makes summary questions answerable. The diversity floor must be
   measured, not assumed.
4. **Interaction with [finding 01](finding-01-unrecoverable-scalar-arrays.md).** Dropped items are
   currently unrecoverable. Better selection reduces the harm but does not remove it; the honest
   framing is "raises the floor", not "solves it".

## Why this fits the task better than a bug fix

- It is a **feature**, matching "identify a gap or a potentially useful new feature".
- It **reuses existing infrastructure** (`headroom/relevance/`) rather than inventing machinery.
- It produces a **quantitative, plotted result** with a clear baseline.
- The primary metric is **deterministic** — a reviewer reproduces the headline number with no API key
  and no LLM variance.
- It admits a genuinely interesting negative-result path: if relevance selection degrades summary
  questions, that trade-off is itself a publishable finding.

---

## Prior art — was this already scoped by the contributors?

Checked directly. **No TODO, no FIXME, no REALIGNMENT entry, no bug-list item** proposes this.
But the answer is more interesting than "nobody thought of it".

### Correction to the framing above

The scorers are **not** unwired in general. The table above said "unused on this path", which is
accurate, but it understates how much of this already exists:

- Rust `SmartCrusher` owns `scorer: Box<dyn RelevanceScorer + Send + Sync>`, defaulting to
  `HybridScorer` (`crusher.rs:121`).
- `planning.rs` is an entire module of query-conditioned selection — query anchors, BM25
  `score_batch`, `relevance_threshold`, `preserve_fields` — every one of them gated on
  `query_context`.
- `TextCrusher` uses `BM25Scorer` too (`text_crusher/crusher.rs:19`).

So the maintainers built query-conditioned selection deliberately and elaborately. They just never
ran it down the scalar path.

What **is** genuinely dead is Python's `headroom/relevance/create_scorer()` — zero internal callers
anywhere. It is a public SDK surface from the initial OSS release (CHANGELOG v0.2.0, Jan 2026),
exposed for library users, not consumed by the proxy. The live scorer is the Rust one.

### The decisive evidence

`crusher.rs:578-590`. `query_context` is **in scope at the dispatch site** and is threaded into the
neighbouring branches:

```rust
ArrayType::StringArray => {
    let strs: Vec<&str> = arr.iter().filter_map(|v| v.as_str()).collect();
    let (crushed, strategy) = crush_string_array(&strs, &self.config, bias);   // <-- no query_context
}
ArrayType::NumberArray => {
    let (crushed, strategy) = crush_number_array(arr, &self.config, bias);     // <-- no query_context
}
ArrayType::MixedArray => {
    let (crushed, strategy) = self.crush_mixed_array(arr, query_context, bias); // <-- passed
}
```

`DictArray` uses it. `MixedArray` uses it. `StringArray` and `NumberArray` are the **only two
branches that drop a variable already in scope**. `self.scorer` is likewise already constructed and
available on the same object. The change is therefore smaller than first estimated.

### Why it was probably left undone

`crushers.rs` is explicitly a **direct port** of Python's `_crush_string_array`, and the port
preserves Python behaviour so faithfully that it deliberately carries a known defect forward:

> `crush_number_array` — **Carries BUG #1** in the percentile calculation (`crushers.rs:217`)

A port disciplined enough to reproduce bugs for parity will not add features. So the omission
originates in the original Python implementation and was frozen in place by the parity rule.

`docs/content/docs/limitations.mdx:13` also lists the scalar-array strategy as
"String dedup + sampling" — sampling is **documented intended behaviour**, not an oversight.

### What this does to the proposal

**Strengthens it.** It is not a bug fix (it is documented, intended behaviour), which answers the
"isn't this just a patch?" objection. And the design precedent is already in-repo: the maintainers
consider query-conditioned selection worth building, so extending it to a path it never reached is
an argued design contribution rather than an unmotivated idea.

### The risk it exposes — new, and real

There may be a **good technical reason** the scalar path was skipped. A dict item is a rich record
with multiple fields for a query to match against. A bare scalar like `"INV-2026-0044"` is a
near-degenerate BM25 document — one token, almost no term statistics. Relevance ranking may simply
not work at this granularity, and exact/substring matching may be the only thing that does.

This is testable and is already covered by the third kill criterion in [PROPOSAL.md](PROPOSAL.md).
It should be measured early, because it decides whether the mechanism is BM25 or something simpler.
