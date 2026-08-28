# Result 03 — Baseline query-conditioned retention (unmodified Headroom)

**Arm:** baseline, unmodified Headroom 0.35.0, Rust `_core` built from repo source
**Cells:** 250 (175 needle + 75 control) · **Runtime:** 190 s · **API cost:** $0
**Harness:** [`repro/qcr_harness.py`](repro/qcr_harness.py) · **Analysis:** [`repro/qcr_analyze.py`](repro/qcr_analyze.py)
**Raw data:** [`data/qcr_baseline.csv`](data/qcr_baseline.csv)

Measured through the live proxy; ground truth is the forwarded request body.
The harness contains **no knowledge of the proposed extension** — it was written and run before any
implementation, so the benchmark cannot have been tuned to the change.

## Headline: retention is decided by position, never by the question

| Position stratum | Cells | Retained | Rate |
|---|---:|---:|---:|
| head (first 30% of K) | 50 | 50 | **100.0%** |
| **interior** | **100** | **28** | **28.0%** |
| tail (last 15% of K) | 25 | 25 | **100.0%** |
| *pooled — do not quote* | *175* | *103* | *58.9%* |

**The pooled 58.9% is an artifact of the position grid and must not be reported as a headline.**
Three of seven sampled positions fall inside Headroom's structural head/tail guarantee, which
inflates the pool. The meaningful number is the **interior** rate: **28.0%**.

## Interior retention collapses as the array grows

| N | Cells | Retained | Rate | Chance (K/N) |
|---:|---:|---:|---:|---:|
| 20 | 20 | 14 | 70.0% | 75.0% |
| 60 | 20 | 9 | 45.0% | 25.0% |
| 150 | 20 | 4 | 20.0% | 10.0% |
| 400 | 20 | 0 | **0.0%** | 4.8% |
| 1000 | 20 | 1 | 5.0% | 3.3% |

At N=400 **not one** of twenty queried interior items survived — below the chance rate, because
stride sampling is deterministic rather than random: an item that falls in a stride gap is excluded
with certainty, not with probability.

## The compression being bought is real

```
forwarded/original bytes: 241,599 / 2,343,811 = 10.3%   (89.7% saving)
compression fired in 175/175 needle cells
```

This is the honest tension. The saving is large and genuine; the cost is that which items survive is
independent of what was asked.

## Retention budget is content-dependent (adaptive K works)

Items retained at N=1000: `invoice_ids` 15, `numeric_ids` 15, `file_paths` 15,
`test_names` 55, `log_lines` 64.

Adaptive K grants richer, more diverse content a larger budget. Verified not to be a measurement
artifact: parsed array length equals substring count exactly for all three spot-checked types.

## Controls confirm query-independence again

The three control questions (`count`, `first`, `spread`) produced **identical** retention in every
cell — same items kept, same head-10 coverage. Consistent with
[improvement-01](improvement-01-query-aware-retention.md)'s premise and with
[result-01](result-01-bm25-scalar-feasibility.md).

These control cells are the regression guard for the extension: the query-aware arm must not
degrade them.

## Method notes / threats

- **`HEADROOM_RATE_LIMIT_ENABLED=false`** was set so the sweep could run at speed. It governs request
  admission, not compression, and will be identical in both arms.
- Every cell uses a **fresh conversation** (unique `system` salt). Required: compression only runs in
  full on session cold start — see [finding-02](finding-02-multiturn-compression-stops.md).
- Retention is measured by membership in the forwarded array, validated against parsed array length.
- These are **synthetic** arrays. Whether real agent traffic produces flat scalar arrays at all is
  still unmeasured and remains the gating question ([PROPOSAL.md](PROPOSAL.md) kill criteria).

---

## CORRECTION (see [result-04](result-04-cache-defeats-query-conditioning.md))

The per-N interior table above was measured with **identical array content across all positions of a
given N**. Headroom's compressed-result cache is keyed on content and omits the query, so cells 2-7
of each size replayed the compression computed for cell 1 rather than compressing under their own
question.

The **headline stratum figures are unaffected** — baseline selection is query-independent, so replay
returns what a fresh compression would have returned. Retention was re-measured with a cell-unique
sentinel appended to defeat the cache; pooled interior retention is **28.0% either way**. The
corrected per-N breakdown is in [result-05](result-05-extension-effect.md) and
[`data/v2_off.csv`](data/v2_off.csv); it differs from the table above (e.g. N=400 is 20.0%, not 0.0%).

Use `v2_off.csv` as the baseline of record.
