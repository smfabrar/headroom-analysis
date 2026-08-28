# Result 11 — Real Claude agent on the Anthropic path, with real cache lapses

**Status:** measured against the live Anthropic API · **Cost:** ~30 real requests, `claude-sonnet-4-5`
**Artifacts:** [`agent_anthropic_bench.py`](repro/agent_anthropic_bench.py) ·
[baseline](data/agent_anthropic_baseline_idle.json) · [fixed](data/agent_anthropic_fixed_idle.json)

**This result tempers [R-07](result-07-recompression-decay.md), [R-09](result-09-why-anthropic-only.md)
and [R-10](result-10-property-sweep.md).** The mechanism reproduces in vivo; the *severity* does not.

---

## Setup

A real `claude-sonnet-4-5` agent calls a `search_logs` tool through Headroom
(`--mode token`). A recording pass-through relays to `api.anthropic.com`, so the model's answers,
the `cache_read_input_tokens` values, and the forwarded bytes are all genuine.

The tool returns 300 CI log lines, each with a unique task id and a unique duration. From turn 2 on,
the user asks for the duration of one specific line that **survived turn 1's compression** — so the
answer is knowable from what the model was actually given. If re-compression later drops that line,
the model must fail.

Anthropic's prompt cache has a ~5 minute TTL, so the benchmark inserts **real 330-second idle gaps**
before every second probe turn. This is the ordinary rhythm of a developer session (thinking, running
tests, reading), and it is what drives `PrefixTracker` back to 0 — the precondition established in
[R-09](result-09-why-anthropic-only.md).

## Result — baseline

```
turn 1: 300/300 log lines survived compression (17213 bytes forwarded of 21399)

  turn  2  retained 300  bytes  13930  cache_read=     0   <- real miss, -19.1%
  turn  3  retained 300  bytes  13930  cache_read=     0   <- flat
  turn  4  retained 300  bytes  13930  cache_read=  8548
  turn  5  retained 300  bytes  13930  cache_read=     0   <- flat
  turn  6  retained 300  bytes  13930  cache_read=  8548
  turn  7  retained 300  bytes  13930  cache_read=     0   <- flat
  turn  8  retained 300  bytes  13930  cache_read=  8548

correct 7/7 turns   retained 300 -> 300
```

**Four genuine cache misses; only the first caused a re-compression.** After that the content reached
a fixed point and never moved again.

## Result — `HEADROOM_IDEMPOTENT_COMPRESSION=1`

Identical protocol, identical model, same idle pattern, same cache-miss pattern:

```
  turn  2  retained 300  bytes  17213  cache_read=     0
  turn  3  retained 300  bytes  17213  cache_read=     0
  turn  4  retained 300  bytes  17213  cache_read=  9503
  ...
  turn  8  retained 300  bytes  17213  cache_read=  9503

correct 7/7 turns   retained 300 -> 300
```

| arm | forwarded bytes, turn 1 → 8 | change |
|---|---|---|
| baseline | 17 213 → 13 930 | **−3 283 bytes (−19.1%)** |
| fixed | 17 213 → 17 213 | **0** |

## What this does and does not establish

**Does:**

- The mechanism is **real against the live API**. A prompt-cache miss on the Anthropic path does
  cause Headroom to re-compress content it had already compressed, at a measured cost of **19.1% of
  the forwarded tool output**.
- The fix **prevents it entirely**, under an otherwise identical run.

**Does not:**

- **The ratchet does not reproduce in vivo.** [R-07](result-07-recompression-decay.md) and
  [R-10](result-10-property-sweep.md) show repeated per-miss losses on synthetic payloads
  (`log_lines` 300 → 62). Here the loss happened **once** and then stopped, despite three further
  cache misses. The synthetic severity is not representative.
- **No harm to the agent was demonstrated.** All 300 log lines survived in both arms and the model
  answered correctly on 7/7 turns in both arms. The fix preserved fidelity; it did not improve
  accuracy, because accuracy was never degraded in this scenario.

## Why the divergence from the synthetic sweep

Unclear, and worth stating as unresolved. Candidate explanations:

- The real payload compressed only 21 399 → 17 213 on turn 1 (a mild 20% reduction retaining every
  probe), whereas the synthetic `log_lines` cell compressed much harder before re-compression bit.
  A gentler first pass may leave content that the second pass largely accepts.
- The synthetic rig used a 20 KB system prompt vs 12 KB here, changing token budgets and therefore
  the compressor's target ratio.
- Real conversation growth (genuine assistant turns) differs from the synthetic filler.

I did not isolate which. It is the most interesting open question left.

## Honest bottom line

The defensible in-vivo claim is narrow:

> On the Anthropic path in token mode, each prompt-cache lapse can cost roughly 19% of an already
> compressed tool output, once per session. The idempotence guard eliminates it. No accuracy impact
> was observed.

That is a real, reproducible, live-API-verified defect and a working fix — and it is considerably
smaller than the synthetic sweep suggested.

## Reproduce

```bash
CAP=/tmp/agent.jsonl; : > $CAP
CAPTURE=$CAP REAL_UPSTREAM=https://api.anthropic.com REC_PORT=9501 \
  python3 research/repro/recording_upstream.py &
headroom proxy --mode token --port 9500 --anthropic-api-url http://127.0.0.1:9501 &

# baseline (add HEADROOM_IDEMPOTENT_COMPRESSION=1 to the proxy for the fixed arm)
python3 research/repro/agent_anthropic_bench.py --arm baseline-idle --turns 7 \
    --idle-every 2 --idle-seconds 330 --port 9500 --capture $CAP
```

Requires `CLAUDE_API_KEY` in `research/.env` (gitignored).
