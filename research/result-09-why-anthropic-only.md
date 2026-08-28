# Result 09 — Why the re-compression decay hits the Anthropic path and not OpenAI

**Status:** mechanism measured directly, not inferred from code reading
**Cost:** $0, fully deterministic, no API key
**Supersedes:** the "cache-warm control" in [result-07](result-07-recompression-decay.md) /
[result-08](result-08-idempotence-fix.md), which was **invalid**. See *Correction* below.

---

## The one-operator difference

Both handlers compute the same two numbers and combine them differently.

`headroom/proxy/handlers/openai.py:3455` — **assignment**:

```python
if not is_cache_mode(self.config.mode):
    openai_frozen_count = comp_cache.compute_frozen_count(messages)
```

`headroom/proxy/handlers/anthropic.py:1644` — **clamp**:

```python
cache_frozen_count = comp_cache.compute_frozen_count(messages)
frozen_message_count = min(frozen_message_count, cache_frozen_count)
```

- `compute_frozen_count` is **content-keyed**: "these leading messages are tool_results I have
  already compressed and cached, so they are stable."
- `prefix_tracker.get_frozen_message_count()` is **provider-confirmed positional truth**, derived
  from Anthropic's `cache_read_input_tokens`.

OpenAI trusts the local content-keyed number outright. Anthropic clamps it to the provider-confirmed
one. The clamp is deliberate and correct — it is the fix for
[issue #327](https://github.com/headroomlabs-ai/headroom/issues/327), where a content-keyed walker
advanced the freeze boundary to `len(messages)` and produced `transforms_applied=[]` on 73% of
requests.

## Measured, side by side

Instrumented with `HEADROOM_FROZEN_TRACE=1` (env-gated, added to both handlers and to
`transforms/pipeline.py`). Identical payload — one 300-item scalar array, 8 turns adding no new
information.

| | OpenAI | Anthropic |
|---|---|---|
| `tracker` | 0 | 0 |
| `compute` | `nmsg-1` | `nmsg-1` |
| **`final`** | **`nmsg-1`** (assign) | **0** (min) |
| Items retained, turns 1→8 | **15 → 15** | **15 → 8** |

```
[frozen] openai    nmsg=18 tracker=0 compute=17 final=17 (assign)
[frozen] anthropic nmsg=17 tracker=0 compute=16 final=0  (min)
```

With `final=0` the entire conversation is live, so `apply_cached()` swaps the previously compressed
tool_result back in and the pipeline compresses **that** — 15 items become 14, and the shorter
result is written back to the cache. The loss is a **ratchet**: it is persisted, so it never recovers.

## The real trigger is a prompt-cache miss

`tracker` is 0 whenever the provider has not confirmed a cached prefix. Per
`headroom/cache/prefix_tracker.py:885-896` that happens on turn 0, when caching is disabled, or when
`_cached_token_count < config.min_cached_tokens` (**default 1024**).

With a warm cache the clamp is a no-op and there is **no decay**:

```
[frozen] anthropic nmsg=17 tracker=16 compute=16 final=16 (min)
retained 15 -> 15 over 8 turns (0% lost)
```

The realistic failure mode is therefore an **intermittent** cache — an agent idling past the ~5-minute
prompt-cache TTL. Simulated with `MISS_EVERY=3` (upstream withholds `cache_read_input_tokens` on
every third turn):

| turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tracker | 0 | 4 | 6 | **0** | 10 | 12 | **0** | 16 | 18 | **0** | 22 | 24 |
| items kept | 15 | 15 | 15 | **14** | 14 | 14 | **13** | 13 | 13 | **12** | 12 | 12 |

**Exactly one item is lost per cache miss, and never recovered.** Warm turns hold the line but cannot
restore what a cold turn removed.

## The fix closes it

`HEADROOM_IDEMPOTENT_COMPRESSION=1` — hash-based "already compressed" guard
([result-08](result-08-idempotence-fix.md)) — under the *same* `MISS_EVERY=3` conditions:

```
turns 1..12: 15 15 15 15 15 15 15 15 15 15 15 15   (241 bytes flat)
```

## Why neither handler is simply "right"

| | protects against #327 | protects against decay |
|---|---|---|
| OpenAI (assign) | ✗ | ✓ |
| Anthropic (min) | ✓ | ✗ |
| + idempotence guard | ✓ | ✓ |

The clamp is the correct cache-safety decision. The defect is that when the clamp bites, the pipeline
re-compresses content it had **already compressed and cached** — the freeze boundary was doing double
duty as the idempotence guard, and it is not one. The existing marker-based guard
(`_is_already_compressed`, `content_router.py:136`) cannot help here because scalar arrays emit no
CCR marker.

---

## Correction — the earlier control was invalid

[result-07](result-07-recompression-decay.md) and [result-08](result-08-idempotence-fix.md) claimed
the decay persisted under `fake_upstream_cached.py` reporting 90% cache reads, and used that to rule
out a test-rig artifact. **That control did not test what it claimed.**

`fake_upstream_cached.py` derived `input_tokens` from `len(raw)//4` on a small synthetic body,
yielding ~340 cached tokens — below `min_cached_tokens = 1024`. `get_frozen_message_count()`
therefore returned 0 for threshold reasons, not for the reason under test. The trace makes this
unambiguous: `tracker=0` on every turn even with cache reads reported.

Fixed by adding `SYSPAD` to `recompression_decay.py` (stable multi-KB system prompt, as real agents
carry). With `SYSPAD=20000` the tracker advances normally and **the decay disappears**.

**What this changes:** the decay is *not* unconditional on the Anthropic path. It is conditional on
prompt-cache misses. That narrows the claim and makes it more precise — and the intermittent-cache
result above is a stronger finding than the original overstated one, because it quantifies a
per-miss cost and shows the loss ratchets.

## Reproduce

```bash
# Anthropic, cold cache -> decay
UPSTREAM_PORT=9401 CAPTURE=/tmp/a.jsonl python3 research/repro/fake_upstream.py &
HEADROOM_FROZEN_TRACE=1 headroom proxy --mode token --port 9400 \
  --anthropic-api-url http://127.0.0.1:9401 &
CAPTURE=/tmp/a.jsonl PORT=9400 N=300 TURNS=8 python3 research/repro/recompression_decay.py

# OpenAI, same payload -> flat
UPSTREAM_PORT=9411 CAPTURE=/tmp/o.jsonl python3 research/repro/fake_upstream_openai.py &
HEADROOM_FROZEN_TRACE=1 headroom proxy --mode token --port 9410 \
  --openai-api-url http://127.0.0.1:9411 &
CAPTURE=/tmp/o.jsonl PORT=9410 N=300 TURNS=8 python3 research/repro/decay_openai_path.py

# Anthropic, intermittent cache -> one item lost per miss
UPSTREAM_PORT=9441 MISS_EVERY=3 CAPTURE=/tmp/m.jsonl python3 research/repro/fake_upstream_cached.py &
HEADROOM_FROZEN_TRACE=1 headroom proxy --mode token --port 9440 \
  --anthropic-api-url http://127.0.0.1:9441 &
CAPTURE=/tmp/m.jsonl PORT=9440 N=300 TURNS=12 SYSPAD=20000 python3 research/repro/recompression_decay.py
```
