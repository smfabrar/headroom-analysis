# Result 07 — Compounding re-compression: an unchanged tool output keeps shrinking

**Status:** verified on **unmodified** Headroom (extension gate off, cache key mode `content`)
**Repro:** [`repro/recompression_decay.py`](repro/recompression_decay.py) · **Data:** [`data/recompression_decay.json`](data/recompression_decay.json)
**Cost:** $0, deterministic, ~40 s

## The result

One tool output (300 invoice IDs) enters a conversation **once**. Every later turn asks a new
question and adds **no new information**. The retained set:

| Turn | Items kept | Delta | tool_result bytes |
|---:|---:|---:|---:|
| 1 | 15 | — | 241 |
| 2 | 14 | −1 | 225 |
| 3 | 13 | −1 | 209 |
| 4 | 12 | −1 | 193 |
| 5 | 11 | −1 | 177 |
| 6 | 10 | −1 | 161 |
| 7 | 9 | −1 | 145 |
| 8 | 8 | −1 | 129 |
| 9–20 | 8 | 0 | 129 |

**47% of the items that survived the first compression are lost to re-compression alone**, purely
as a function of conversation length. Identical with the extension enabled and disabled, so this is
upstream behaviour.

## Mechanism

Two pieces, both intended individually:

1. **Compressed content is substituted back into the conversation.**
   [`cache/compression_cache.py:326`](../headroom/cache/compression_cache.py) — `apply_cached()`
   walks the messages and swaps each tool result for its cached compressed form. The handler calls
   it as *"Zone 1: Swap cached compressed versions"*
   ([`openai.py:3446`](../headroom/proxy/handlers/openai.py)).

2. **The substituted content is then compressed again.** Traced directly at the crusher entry
   point:

```
[SC] len(content)=5100  query='Is INV-2026-0061 in the invoice list?'
[SC] len(content)=241   query='Now: is INV-2026-0121 in that same list?'
[SC] len(content)=225   query='Now: is INV-2026-0181 in that same list?'
[SC] len(content)=209   query='Now: is INV-2026-0241 in that same list?'
```

Turn 2 does not compress the original 5,100-character array. It compresses turn 1's 241-character
*output*. Each pass drops roughly one more item.

The decay stops at exactly 8 because `crush_string_array` passes through untouched at `n <= 8`
([`crushers.rs:120`](../crates/headroom-core/src/transforms/smart_crusher/crushers.rs)). The floor
is an accident of that guard, not a designed stopping point.

## Why this matters

**It is loss without benefit.** Turns 2–8 discard information while adding none. The tokens saved
are marginal (241 → 129 bytes) against seven further lossy passes over data the model may still
need.

**It makes query-conditioned selection structurally impossible after turn 1.** Whatever the query
ranks on turn 2, it can only rank the ~15 survivors of turn 1's compression — chosen under turn 1's
question. This is why [result-05](result-05-extension-effect.md)'s single-turn gain (28% → 100%)
does not carry into a multi-turn session: by the time the second question arrives, its target is
already gone.

**The loss is unrecoverable on this path.** Scalar arrays get no CCR marker and no retrieval
handle ([finding-01](finding-01-unrecoverable-scalar-arrays.md)), so nothing signals that the list
was truncated, let alone truncated repeatedly.

## Relation to the other findings

This **supersedes** the cache-key hypothesis in
[result-04](result-04-cache-defeats-query-conditioning.md) as the explanation for multi-turn
staleness. A three-arm test (`content` / `query` / `anchors` cache keys,
[`repro/cache_key_ab.py`](repro/cache_key_ab.py)) produced **identical results in all three arms**
(1/8 retained, mean 11.5 items) — the freeze is not in the cache key. Result-04's narrower claim
still stands on its own evidence: the key genuinely omits the query, and identical content with a
different question returns byte-identical output within a single turn.

## Threats to validity

- **Synthetic array**, Anthropic `/v1/messages` path, `--mode token`. In the default `--mode cache`
  no compression runs at all ([result-06](result-06-in-vivo-null.md)).
- **One content type** (invoice IDs). The −1/turn rate and the floor at 8 are specific to
  `crush_string_array`; other compressors will have different decay profiles. Unmeasured.
- **Whether this is intended** is not established. Substituting compressed content forward is
  deliberate and sensible on its own; re-compressing the substituted result may simply be an
  unnoticed interaction. No upstream issue was found describing it.
- **No LLM-side harm measured.** That fewer items are retained is shown; that a model therefore
  answers worse is not.

---

## SCOPE CORRECTION (see [result-08](result-08-idempotence-fix.md))

The decay is **specific to the Anthropic `/v1/messages` handler**, and narrower than this page
first implies. Controls measured afterwards:

| Condition | Decay? |
|---|---|
| Anthropic path, JSON scalar array | yes (15 → 8) |
| Anthropic path, grep-shaped text | no |
| Anthropic path, prose | no (never compressed) |
| **OpenAI path, identical JSON array** | **no** (15, flat) |

Same payload, different endpoint, different behaviour — so this is not a property of
`crush_string_array` or of the payload.

The root cause is also sharper than "re-compression happens": Headroom **already has** an
idempotence guard (`_is_already_compressed`), but it detects compressed content only by CCR marker,
and scalar arrays are emitted without one. See [result-08](result-08-idempotence-fix.md).

---

## ⚠ CORRECTION (superseded in part by [result-09](result-09-why-anthropic-only.md))

The "cache-warm control" reported above — `fake_upstream_cached.py` reporting 90%
`cache_read_input_tokens`, decay persisting identically — **was invalid**. That rig produced ~340
cached tokens, below `PrefixTracker.min_cached_tokens = 1024`, so
`get_frozen_message_count()` returned 0 for threshold reasons rather than for the reason under test.
Direct instrumentation (`HEADROOM_FROZEN_TRACE=1`) shows `tracker=0` on every turn of that run.

With a genuinely warm cache (`SYSPAD=20000`), **the decay does not occur**. The decay is conditional
on prompt-cache misses, not unconditional on the Anthropic path. Under an intermittent cache
(`MISS_EVERY=3`) exactly one item is lost per miss and never recovered.

See [result-09](result-09-why-anthropic-only.md) for the measured mechanism and revised claim.
