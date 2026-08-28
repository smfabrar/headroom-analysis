# Finding 02 — Compression fires once per conversation, then stops

**Status:** reproducible, mechanism NOT yet identified · **Strength:** high (if it survives real-agent validation)
**Cost to verify:** zero (no API key) · **Date:** 2026-08-21 · **Version:** `headroom-ai` 0.36.2

---

## Claim

In a **growing multi-turn conversation** — the actual coding-agent workload — Headroom compresses
the tool output on the **first** request and then forwards every subsequent turn's newest tool
output **verbatim**, indefinitely.

Because a coding-agent session's cost is dominated by the *new* tokens added each turn, savings
decay toward zero as the session grows.

## Evidence

Ground truth = bytes captured at a fake Anthropic upstream (`repro/fake_upstream.py`).

### A. Growing conversation — only turn 0 is compressed

`repro/multiturn_inversion.py`, payload = 60 dicts × 60 random words (~34.6 KB) per turn:

```
request at turn 0
   tool_result from turn 0:  34610 ->   2430  ( 93.0% saved)  <-- NEWEST
request at turn 1
   tool_result from turn 0:  34610 ->   2430  ( 93.0% saved)
   tool_result from turn 1:  34610 ->  34610  (  0.0% saved)  VERBATIM  <-- NEWEST
request at turn 2
   turn 0: 93.0% saved · turn 1: 0.0% · turn 2: 0.0% VERBATIM        <-- NEWEST
request at turn 3
   turn 0: 93.0% saved · turns 1,2,3: 0.0%                            <-- NEWEST
```

This is the inverse of the documented design, which states compression targets the newest
delta (the "live zone") and forwards older turns byte-faithfully.

### B. The compressor itself is correct — it is not a structural limit

Sent as the **first** request to a **fresh** proxy, every conversation length compresses the
newest tool result correctly (`repro/msgcount_first_request.py`):

```
FIRST request to fresh proxy,  3 messages (1 turn ): newest 93.1% saved  COMPRESSED
FIRST request to fresh proxy,  6 messages (2 turns): newest 93.1% saved  COMPRESSED
FIRST request to fresh proxy,  9 messages (3 turns): newest 93.1% saved  COMPRESSED
FIRST request to fresh proxy, 12 messages (4 turns): newest 93.1% saved  COMPRESSED
```

So message count, conversation length, and payload shape are **not** the cause.

### C. The state is keyed to the conversation, not the process

Same proxy, three interleaved conversations (`repro/isolate_state.py`):

```
Conversation A (incremental):  turn 0: 93.0%   turn 1: 0.0%   turn 2: 0.0%
Conversation B (brand new):    turn 0: 93.0%   turn 1: 0.0%
Conversation A, fresh prefix:  turn 0: 93.0%
```

A brand-new conversation compresses again on its first request. So the proxy is not globally
"stuck" — something is remembered **per conversation prefix** and suppresses compression on
every subsequent extension of that prefix.

## Economic consequence (if it holds)

For a session of N turns each adding T tokens of tool output, only turn 0 is compressed:

| Session length | Tool-output tokens saved |
|---|---|
| 1 turn | ~93% |
| 4 turns | ~23% |
| 10 turns | ~9% |
| 40 turns (realistic agent session) | ~2% |

The README claims *"15-20% fewer tokens (for coding agents)"*. If this finding survives
real-agent validation, that figure would not be attainable on long sessions.

It also explains why the project's own accuracy benchmarks would not catch it: GSM8K,
TruthfulQA, SQuAD and BFCL are all **single-turn**, which is exactly the case that works.

## Mechanism — IDENTIFIED

`headroom/proxy/handlers/anthropic.py:1837-1885`. In the default `cache` mode there are two branches:

```python
if not previous_original_messages and tracker_frozen_count == 0:
    # session cold start -> run FULL compression
    ...
    transforms_applied = [...] + ["cache_mode:cold_start_full"]
else:
    delta = self._extract_cache_stable_delta(
        original_client_messages, previous_original_messages, previous_forwarded_messages)
if delta is not None:
    ... compress only the delta ...
```

- **Turn 0** takes the cold-start branch — full compression, tagged `cache_mode:cold_start_full`.
- **Turn 1+** takes the `_extract_cache_stable_delta` branch, which in our runs yields no
  compressible delta, so `transforms_applied` is `[]` and the newest tool output is forwarded verbatim.

Confirmed by the proxy's own `/transformations/feed`:

| turn | orig tok | optimized | tokens_saved | savings% | transforms_applied |
|---|---|---|---|---|---|
| 0 | 17186 | 1701 | 15485 | 90.1% | `router:tool_result:smart_crusher`, `cache_mode:cold_start_full` |
| 1 | 34358 | 18873 | 15485 | 45.1% | `[]` |
| 2 | 51477 | 35992 | 15485 | 30.1% | `[]` |
| 3 | 68673 | 53188 | 15485 | 22.5% | `[]` |

**Ruled out:** `read_maturation` (the deliberate hold-back module) is `RolloutChannel.BETA`
(`headroom/rollout.py:111`), i.e. off on the default `stable` channel. This is not intentional hold-back.

**Prior art in the same code path.** An inline comment at `anthropic.py:1890` documents a
previously-fixed sibling bug in the same delta path: *"the router's per-block 'never compress an
explicit cache key' guard ... doesn't skip the ONLY compressible content every turn (route_counts
had cache_control_protected == the whole delta -> 0%)"*. So a 0%-savings failure of the stable-delta
path has happened before and been patched once. This looks like a surviving sibling.

## Reproduce

```bash
python research/repro/fake_upstream.py &
ANTHROPIC_TARGET_API_URL=http://127.0.0.1:8799 HEADROOM_SKIP_UPSTREAM_CHECK=1 \
  headroom proxy --port 8792 &
python research/repro/multiturn_inversion.py     # A
python research/repro/isolate_state.py           # C
```

## What would falsify this / open work

- [x] ~~Client-realism confound~~ **ELIMINATED.** Re-ran with (a) client-placed `cache_control`
      on the last block, (b) `anthropic-beta: prompt-caching-2024-07-31`, (c) a realistic system
      block. All four variants decay identically (`repro/faithful_client.py`):

      ```
      variant                          turn0    turn1    turn2    turn3
      V1 baseline                      89.5%     0.0%     0.0%     0.0%
      V2 + client cache_control        89.2%     0.0%     0.0%     0.0%
      V3 + cache_control + beta hdr    88.6%     0.0%     0.0%     0.0%
      V4 + all + system prompt         89.4%     0.0%     0.0%     0.0%
      ```
- [ ] **Real agent validation still wanted** (Claude Code via `headroom wrap claude`) — a real
      client may drive session tracking differently again. Lower risk now, but not zero.
- [ ] Identify the mechanism in code; confirm with a debug build rather than inference.
- [ ] Check whether OpenAI Chat/Responses paths share the behaviour.
- [ ] Check `--mode token` (this was all default `cache` mode).
- [ ] Check against the fork's `main` (ahead of the 0.36.2 PyPI wheel tested here).

## Caveats

- Synthetic conversations only.
- Anthropic `/v1/messages` path only, default `cache` mode.
- The 93% figure is payload-specific; the load-bearing number is **0.0% on turns 1+**, not the 93%.
