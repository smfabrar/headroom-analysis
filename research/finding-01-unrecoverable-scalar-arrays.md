# Finding 01 — Scalar JSON arrays are discarded with no recovery path

**Status:** verified on the production proxy path · **Strength:** medium-high · **Cost to verify:** zero (no API key)
**Date:** 2026-08-21 · **Version tested:** `headroom-ai` 0.36.2 (PyPI wheel, Rust core loaded)

---

## Claim

For JSON arrays of **scalars** (strings or numbers), Headroom discards most elements and:

1. writes **nothing** to the CCR store,
2. emits **no** retrieval marker into the tool result,
3. still registers the `headroom_retrieve` tool on the request.

The discarded elements are therefore **unrecoverable in principle** — not merely expired or evicted.
The model receives a syntactically valid, complete-looking array and has no signal that anything was removed.

This contradicts the documented guarantee.

## Documented guarantee this contradicts

From [`docs/content/docs/ccr.mdx`](../docs/content/docs/ccr.mdx):

> "Unlike traditional lossy compression, CCR guarantees that every piece of original data remains accessible."
> "Nothing is ever thrown away."

From [`headroom/transforms/smart_crusher.py`](../headroom/transforms/smart_crusher.py) (`lossless_only` docstring):

> "The output is always marker-free and fully byte-recoverable: rows are never dropped and opaque cells render inline."

`--lossless` mode does **not** prevent the loss (see evidence below).

## Evidence

Captured by pointing the proxy at a fake Anthropic upstream that records the exact
forwarded bytes (`research/repro/fake_upstream.py`), so this is what the **model actually receives**,
not a library-level approximation.

### A. Flat 15-item cap regardless of input size

| Input (string IDs) | Reaches model | Deleted | Marker in tool_result | Stored in CCR |
|---|---|---|---|---|
| 20 | 15 | 5 | no | no |
| 40 | 15 | 25 | no | no |
| 100 | 15 | 85 | no | no |
| 300 | 15 | 285 | no | no |

Mechanism: `max_items_after_crush: int = 15` (`headroom/transforms/smart_crusher.py`).

### B. Concrete instance (40 invoice IDs)

Sent:
```
["INV-2026-0001", "INV-2026-0002", ... "INV-2026-0040"]      (40 items)
```
Forwarded to model:
```
["INV-2026-0001","INV-2026-0002","INV-2026-0003","INV-2026-0004","INV-2026-0007",
 "INV-2026-0010","INV-2026-0013","INV-2026-0016","INV-2026-0019","INV-2026-0022",
 "INV-2026-0025","INV-2026-0028","INV-2026-0031","INV-2026-0039","INV-2026-0040"]   (15 items)
```
25 deleted. No count, no marker, no hash. Asked "is INV-2026-0021 present?", the only
answer derivable from what the model sees is "no" — which is wrong.

### C. Nothing is written to the store

Controlled test with a unique fingerprint (`ZQX7-UNIQUE-TOKEN-NNNN`, 60 items):

```
CCR store entry_count before : 603
CCR store entry_count after  : 603      (delta 0)
grep of ~/.headroom/ccr_store.db        : fingerprint NOT FOUND
```

So this is not "stored but the key was withheld" — CCR is never invoked on this path.

### D. `--lossless` does not mitigate

```
proxy --lossless, 300-element string array -> 19 kept, 0 markers
```

### E. Contrast — other paths behave correctly

| Shape | Behaviour | Recoverable |
|---|---|---|
| Uniform dict rows | lossless CSV-schema compaction, `[40]{amount:int,invoice:string,status:string}` + all 40 rows | n/a — nothing lost |
| Dicts with long prose | 300 CCR entries created, 300 markers emitted | yes |
| **Scalar arrays** | **elements deleted, no store write, no marker** | **no** |

The CCR mechanism demonstrably works. This path simply does not use it.

### F. Mitigating factor (reported honestly)

The statistical safety net **does** fire: an `ERROR: ... ENOSPC-7742` needle buried at index 173
of a 300-element array survived compression. Blast radius is smaller than the raw percentages
suggest — anomalous/error-bearing elements are preferentially retained.

## Reproduce

```bash
python research/repro/fake_upstream.py &                     # records forwarded bytes
ANTHROPIC_TARGET_API_URL=http://127.0.0.1:8799 \
  HEADROOM_SKIP_UPSTREAM_CHECK=1 headroom proxy --port 8792 &
python research/repro/scalar_array_loss.py                   # prints the table above
```

## Interpretation — two readings, both leave a defect

- **Oversight.** Every other lossy path calls CCR; this one does not. Looks like a gap.
- **Deliberate.** Docs do say string arrays get "dedup + adaptive sampling"; they may consider
  scalar elements low-value.

Either way there is a defect: if deliberate, the reversibility guarantee and the `--lossless`
contract are false as written. So it is either a code bug or a documentation bug.

## Why this might be more than a bug

The deeper gap: **no compression path declares what kind of loss it caused.** Lossless reshaping,
CCR-backed removal, and unrecoverable deletion are indistinguishable to the system — all report
"success, N tokens saved." There is no vocabulary to express, enforce, or measure recoverability,
which is why this went unnoticed and why no metric for it exists.

Candidate extension: a **recoverability contract** (`LOSSLESS` / `RECOVERABLE` / `UNRECOVERABLE`)
declared by every path, enforced at the dispatcher, with a strict mode that refuses to discard
what it cannot return, plus an audit of the loss-class distribution of real traffic.

## Open questions blocking a strength upgrade

- [ ] **Does upstream already know?** Check git log, issues, CHANGELOG.
- [ ] **Do real coding agents emit scalar arrays?** If real tool outputs are overwhelmingly dicts,
      this is a curiosity, not a live risk. Must measure real traffic shape distribution.
- [ ] Is the 15-item cap reached before or after the error-preservation pass in all cases?

## Caveats

- All evidence to date uses **synthetic payloads**.
- Tested on the Anthropic `/v1/messages` path only; OpenAI Chat/Responses paths not yet checked.
- Single version (0.36.2); not checked against `main` of the fork, which is ahead of PyPI.
