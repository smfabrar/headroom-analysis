# Result 10 — Multi-turn cross-handler property sweep

**Type:** capability extension (a test harness Headroom does not have) + its first findings
**Cost:** $0, no API key, fake upstreams only
**Artifacts:** [`property_sweep.py`](harness/property_sweep.py) ·
[`analyze_sweep.py`](harness/analyze_sweep.py) ·
[`aggregate_repeats.py`](harness/aggregate_repeats.py) ·
data: [`property_sweep_r1.json`](data/property_sweep_r1.json),
[`r2`](data/property_sweep_r2.json), [`r3`](data/property_sweep_r3.json)

---

## The gap this fills

Headroom's own suite ([result-02](result-02-existing-eval-suite.md)) is **single-turn and
single-provider**: it asks whether one compression preserves enough information to answer one
question. Verified absences in `tests/`:

- `tests/parity/` compares **Python↔Rust** only — no OpenAI↔Anthropic handler comparison.
- No multi-turn compression regression test.
- No test asserting compression is idempotent.

So a defect that only appears on the *second* time a payload is compressed, or only on *one*
provider path, is structurally invisible to the existing suite. This harness expresses exactly those
properties.

## Properties asserted

| | Property |
|---|---|
| **P1** | **Idempotence** — re-sending an unchanged tool output must forward unchanged bytes. `compress(compress(x)) == compress(x)`. Checked on **both** probe retention and byte count. |
| **P2** | **Cross-handler equivalence** — same payload, same cache regime, same arm must behave the same on both provider paths. |
| **P3** | **Turn-index independence** — retention must not depend on elapsed turns (implied by P1; it is the property an agent actually feels). |

## Matrix

2 providers × 3 prompt-cache regimes × 2 arms × 6 content types × 10 turns
= **72 cells / 720 requests per pass**, run **3 times** (216 cell-runs).

- **providers**: `anthropic` (`/v1/messages`), `openai` (`/v1/chat/completions`)
- **regimes**: `cold` (upstream never reports cache reads), `warm` (90% cache reads),
  `intermittent` (90%, but a miss every 3rd turn — simulates the ~5 min TTL lapsing)
- **arms**: `baseline`, `fixed` (`HEADROOM_IDEMPOTENT_COMPRESSION=1`)
- **content types**: `json_string_array`, `json_number_array`, `json_dict_array`, `log_lines`,
  `search_results`, `plain_text` (300 items each)

Every conversation carries a 20 KB stable system prompt, because
`PrefixTracker.min_cached_tokens` defaults to **1024** — without realistic prefix bulk every regime
silently degenerates to `cold` (the mistake that invalidated the earlier control in
[result-09](result-09-why-anthropic-only.md)).

## Methodology guards

Two guards materially changed the numbers, and both were added *after* a first pass produced
inflated results:

1. **Vacuous cells are excluded from the denominator.** A cell where compression never fired
   trivially satisfies P1 while testing nothing. 16 of 72 cells are vacuous and are reported
   separately, not as passes.
2. **A single pass cannot support a violation count.** `anthropic/intermittent/json_string_array`
   held under full-matrix load but failed in three isolated repeats. Request latency differs under
   load and `idle_seconds` feeds Headroom's net-cost policy, so timing can change decisions. Only
   verdicts stable across **all three** repeats are reported as findings; anything that flips is
   reported as **flaky and never counted as a pass**.

## Results

```
repeats                        : 3
cells per repeat               : 72
stable vacuous (tested nothing): 16
stable holds                   : 47
STABLE VIOLATIONS              : 5
flaky                          : 4
errors                         : 0

meaningfully checked           : 56
violation rate (stable)        : 5/56 = 9%
stable violations by provider  : {'anthropic': 5}
stable violations by arm       : {'baseline': 5}
```

### The five stable violations

| regime | content type | probes retained | forwarded bytes | payload |
|---|---|---|---|---|
| cold | `json_string_array` | 15 → **8** (−47%) | 376 → 201 | 7 800 |
| cold | `log_lines` | 300 → **62** (−79%) | 18 323 → 3 904 | 22 509 |
| cold | `search_results` | 300 → 300 | 13 432 → **7 970** (−41%) | 20 009 |
| intermittent | `log_lines` | 300 → **62** (−79%) | 18 323 → 3 904 | 22 509 |
| intermittent | `search_results` | 300 → 300 | 13 432 → **8 009** (−40%) | 20 009 |

All five are `anthropic` + `baseline`. **The fix arm has zero violations and zero flaky cells.**

### The single strongest number

Across **216 cell-runs**, every violation and every instance of nondeterminism is confined to
`anthropic` + `baseline`. The OpenAI path and both fixed arms were stable in all three repeats.

## What this adds beyond the earlier findings

1. **The defect is not scalar-array-specific.** [result-07](result-07-recompression-decay.md)
   framed it around JSON scalar arrays. `log_lines` loses **79%** of what the first compression
   retained, and `search_results` loses 41% of its bytes — both worse than the scalar array, and
   both far more representative of real agent tool output (build logs, test runs, grep results).
2. **`search_results` is a violation class a retention-only check misses.** Every probe token
   survives while bytes fall 41%. Measuring only "did my needle survive" would have scored this a
   pass.
3. **The decay converges, it does not run away.** Each series reaches a fixed point — `log_lines`
   after one re-compression, `json_string_array` at 8 items (the `n <= 8` passthrough guard). The
   honest claim is a **one-off cliff on re-compression**, not unbounded erosion.
4. **Baseline Anthropic compression is nondeterministic.** Four cells changed verdict between
   identical repeats; `json_number_array` swung 15 → 9 in one repeat and held in the other two. The
   fixed arm was deterministic in all three. This is itself a defect and was not previously known.

### Cross-handler divergence (P2)

9 divergences per pass. Beyond the violations, the two paths disagree on *whether to compress at
all*: `search_results` compresses to 13 432 bytes on Anthropic and is left untouched at 20 009 bytes
on OpenAI. Same payload, same config, same mode.

## Threats to validity

- **Fake upstreams.** Cache-read reporting is synthetic. It is calibrated to the thresholds the code
  actually reads (`cache_read_input_tokens`, `prompt_tokens_details.cached_tokens`,
  `min_cached_tokens = 1024`), but no real provider was in the loop.
- **Synthetic payloads.** Content types are generated, not captured from a real agent. The
  [in-vivo A/B](result-06-in-vivo-null.md) with a real agent was null on the OpenAI path, which is
  consistent with these results — OpenAI has no stable violations here either.
- **Flakiness is characterised, not explained.** I show it exists and confine it to
  `anthropic`+`baseline`; I have not isolated the exact timing input that causes it.
- **The `fixed` arm is my own change**, so "the fix closes all five" is a claim about my patch under
  my harness. It is env-gated and default-off, and the baseline arm is upstream behaviour.

## Reproduce

```bash
# one pass
python3 research/harness/property_sweep.py --turns 10 --items 300 \
    --out research/data/property_sweep_r1.json
python3 research/harness/analyze_sweep.py research/data/property_sweep_r1.json

# three passes + stability aggregation (the reportable result)
for r in 1 2 3; do
  python3 research/harness/property_sweep.py --turns 10 --items 300 \
      --out research/data/property_sweep_r$r.json
done
python3 research/harness/aggregate_repeats.py research/data/property_sweep_r*.json
```
