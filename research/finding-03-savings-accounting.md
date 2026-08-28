# Finding 03 — Savings accounting inconsistencies (NOT YET A CLAIM)

**Status:** observed, needs careful analysis before claiming · **Date:** 2026-08-21

Surfaced while investigating [finding 02](finding-02-multiturn-compression-stops.md). Recorded so it
is not lost, but **deliberately not claimed** — there is a defensible reading for part of it.

## Observations

After 16 requests (4 conversations x 4 turns), `/stats` reported:

```
summary.compression.requests_compressed   : 16
compressions_by_strategy                  : {"smart_crusher": 4}      <-- only 4 compressor runs
summary.compression.total_tokens_removed  : 246992
tokens_saved_by_strategy                  : {"smart_crusher": 40973}  <-- 6x smaller
tokens.savings_percent                    : 99.94
summary.cost.savings_pct                  : 99.8   ("$0.74 saved")
```

1. `requests_compressed = 16` while only **4** requests actually invoked a compressor
   (`transforms_applied: []` on the other 12 — see finding 02).
2. `total_tokens_removed` (246,992) is ~6x `tokens_saved_by_strategy` (40,973).
3. `savings_percent: 99.94%` — Headroom did not remove 99.94% of tokens.

## The defensible counter-reading (why this is not yet a claim)

Per request, the forwarded body genuinely *is* ~15,485 tokens smaller than what the client sent,
because turn 0's block keeps being re-compressed deterministically to preserve the cached prefix.
Billing is per request, so summing that saving across requests is **arguably legitimate** — you
really did send 15,485 fewer tokens on each of the four calls.

Under that reading, `total_tokens_removed` is defensible and only these are wrong:

- `requests_compressed` counting requests where no compressor ran,
- `savings_percent: 99.94%`, whose numerator and denominator appear to come from different
  populations (`proxy_attempted_tokens` was 683,849 against a `total_tokens_before` of 247,152).

## Before this can be claimed

- [ ] Derive exactly how `savings_percent` and `total_tokens_removed` are computed
      (`headroom/proxy/savings_tracker.py`, `savings_ledger.py`, `persistent_metrics.py`).
- [ ] Decide whether per-request summation is the intended (and honest) accounting model.
- [ ] Check against a real provider's reported `usage` rather than Headroom's own estimator.
- [ ] Distinguish a *display* bug from an *accounting* bug — they carry very different weight.

## Why it might matter

If reported savings scale with conversation length while actual compression work does not, then
published savings figures would be inflated by roughly the average session length. That would be a
significant claim — which is exactly why it needs to be nailed down properly rather than asserted
from a single 16-request sample on a synthetic workload.
