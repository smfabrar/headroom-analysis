# Result 01 — Can BM25 separate items in a scalar array?

**Kill-criterion test for [improvement-01](improvement-01-query-aware-retention.md).**
Deterministic, no API key. Script: [`repro/bm25_scalar_feasibility.py`](repro/bm25_scalar_feasibility.py)

The worry: a dict item is a rich record with many fields; a bare scalar like `INV-2026-0044` is a
near-degenerate BM25 document — one or two tokens, almost no term statistics. If BM25 cannot rank
the queried item into the K budget, the proposed mechanism is wrong and the design must change.

## Setup

`N=200`, `K=15` (Headroom's `max_items_after_crush` default). Five content types. Seven target
positions per type (head, stride-aligned, stride-gap, mid, tail). Two query styles:

- **exact** — the agent quotes the identifier verbatim: *"What is the status of invoice INV-2026-0044?"*
- **descriptive** — the agent describes it semantically, no literal overlap:
  *"Which invoice was rejected by the payment processor?"*

## Result

```
N=200  K=15  random baseline = K/N = 7.5%

content type   query    in top-K  median rank  worst rank
------------------------------------------------------------
invoice_ids    exact   7/7                  1           1
invoice_ids    descr   2/7                 49         199
file_paths     exact   7/7                  1           1
file_paths     descr   1/7                 70         199
log_lines      exact   7/7                  1           2
log_lines      descr   2/7                 49         199
test_names     exact   7/7                  1           1
test_names     descr   2/7                 49         199
numeric_ids    exact   7/7                  1           1
numeric_ids    descr   2/7                 49         199
------------------------------------------------------------
EXACT-mention queries : 35/35 = 100% retained in top-K
DESCRIPTIVE queries   :  9/35 =  26% retained in top-K
Headroom today (K/N)  :             8% (query-independent)
```

## The 26% is not real — verified

The descriptive number looked like weak signal. It is not. Probing the invoice case directly:

```
distinct scores: 1   min/max: 0.0 0.0
score counts: [(0.0, 200)]
top-15 indices: [0, 1, 2, ... 14]
```

**Every one of the 200 items scores exactly 0.0.** The ranking collapses to original index order, so
the two targets that happen to sit at positions 0 and 3 fall inside the top-15 by position alone —
2 of 7 = 29%, which is the 26% observed. It is a tie-breaking artifact, and it is retention Headroom's
existing head-preservation already provides.

**Honest reading: BM25 contributes zero signal on descriptive queries over opaque identifiers.**

## What this means for the design

1. **The degeneracy worry was wrong.** Exact-mention queries are not merely workable — they are
   near-perfect: 35/35, median rank **1**. IDF makes a quoted identifier maximally discriminative
   precisely *because* the documents are short.

2. **The mechanism has a sharp, honest boundary.** It helps when the query contains a literal token
   from the item, and not otherwise. That is a real limitation and must be stated as one.

3. **The fallback trigger is unambiguous and free.** The failure mode is not "bad ranking" but
   "all scores identically zero". Detecting flat/zero scores costs nothing and makes the required
   graceful fallback to current sampling behaviour trivially correct. This is a *better* safety
   story than a scorer that returns confident-but-wrong rankings.

4. **Richer scalars behave differently and need watching.** `file_paths` under descriptive queries
   scored 1/7 with median rank 70 — a different pattern from the pure-tie signature (2/7, median 49).
   So partial lexical overlap does produce non-zero scores there, and they pointed at the *wrong*
   items. Query-aware selection can therefore be actively worse than sampling on that combination.
   This is the strongest argument for the diversity floor and for the control tasks.

## The question this hands to the traffic capture

The extension's value now reduces to one measurable quantity:

> **How often does a real coding agent's query quote an identifier that appears verbatim in a
> scalar tool-output array?**

High → large, well-founded win. Low → the mechanism is correct but rarely fires, and that is the
honest headline. Either way the answer comes from [task #2](PROPOSAL.md), the traffic capture,
which is now doubly load-bearing.

## Caveat

Run against the **Python** `BM25Scorer`. The live proxy path uses the Rust port, which the source
documents as a mirror of the Python implementation. Parity was not independently verified here;
the numbers should be re-confirmed against the Rust scorer before publication.
