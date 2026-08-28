# Result 08 — The fix, and how far it reaches

**Change:** idempotence guard, env-gated `HEADROOM_IDEMPOTENT_COMPRESSION=1`, default off
**Repro:** [`repro/decay_generality.py`](repro/decay_generality.py),
[`repro/agent_decay_bench.py`](repro/agent_decay_bench.py),
[`repro/decay_openai_path.py`](repro/decay_openai_path.py)

## Root cause: an existing guard with a hole

Headroom already has an idempotence guard,
[`content_router.py:136`](../headroom/transforms/content_router.py):

```python
def _is_already_compressed(text: str) -> bool:
    """True if ``text`` still carries a CCR retrieval marker.

    Re-compressing such a block is never right. ...
    """
    return any(marker in text for marker in _ALREADY_COMPRESSED_MARKERS)
```

It detects "already compressed" **solely by the presence of a CCR marker**
(`<<ccr:`, `Retrieve more: hash=`, `Retrieve original: hash=`).

Scalar arrays are compressed **without any marker**
([finding-01](finding-01-unrecoverable-scalar-arrays.md)). Measured on every compressed output in
the decay run:

```
len=241  _is_already_compressed=False  head=["INV-2026-0001","INV-2026-0002",...
len=225  _is_already_compressed=False  ...
len=209  _is_already_compressed=False  ...
```

The guard cannot see them, so they are re-compressed on every turn. The maintainers' own comment
says re-compressing "is never right" — this is a gap in the detection, not a design decision.

## The fix

Recognise a compression output by **identity rather than by marker**: the cache records a hash of
every string it emits (`mark_output`), and the block path skips content it previously produced
(`is_output`). Independent of marker emission, so it covers the paths markers do not.

Effect on the decay (Anthropic path, 300-item array):

| Turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| **guard off** (upstream) | 241 | 225 | 209 | 193 | 177 | 161 | 145 | 129 | 129 | 129 |
| **guard on** | 241 | 241 | 241 | 241 | 241 | 241 | 241 | 241 | 241 | 241 |

Turn-1 compression is unchanged (5,100 → 241 bytes), so **no savings are given up**. Only the
repeated re-compression is suppressed.

## How far the decay reaches — three negative controls

The decay is much narrower than it first appeared. Each of these was measured, not assumed:

| Condition | Decay? | Evidence |
|---|---|---|
| Anthropic path, JSON scalar array | **yes** | 15 → 8 items, −1/turn |
| Anthropic path, grep-shaped text | no | 17,685 bytes, flat for 8 turns |
| Anthropic path, prose | no | never compressed at all |
| **OpenAI path, identical JSON array** | **no** | 15 items, flat for 10 turns |

The last row is the important one: the **same payload** through
`/v1/chat/completions` does not decay. So this is a property of the **Anthropic `/v1/messages`
handler**, not of the payload or of `crush_string_array`.

## Real-agent benchmark: no effect, and why

Function-calling agent, `gpt-4o-mini`, 240-file repo, 8 follow-up turns about files that survived
turn 1. Both arms:

```
arm off : accuracy 8/8 = 100%   items in context 16 -> 16
arm on  : accuracy 8/8 = 100%   items in context 16 -> 16
```

**No difference — as expected**, because that agent speaks the OpenAI path, which the controls above
show does not decay. This is a null result that *confirms* the scoping rather than contradicting the
finding.

## What is still missing

Demonstrating the decay with a **real agent** requires an Anthropic-path client (Claude Code, or any
Anthropic SDK agent). That has not been run. Until it is, the decay is established:

- **mechanistically** — traced to `apply_cached` swapping compressed content back in, then the
  router compressing it again, with the marker-based guard blind to it;
- **empirically on synthetic traffic** through the real proxy;
- **not** on live agent traffic.

The honest claim is therefore: *a reproducible defect on the Anthropic handler, with a working
minimal fix, whose real-world frequency is unmeasured.*

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
