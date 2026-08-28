# Result 06 — In vivo, the extension has no effect. The kill criterion fired.

**Agent:** function-calling coding agent, `gpt-4o-mini`, 240-file Python repo
**Proxy:** Headroom `--mode token` (compression on) · **Arms:** `HEADROOM_QUERY_AWARE_SCALARS` off/on
**Data:** [`data/vivo_ab_results.json`](data/vivo_ab_results.json) · **Harness:** [`repro/vivo_ab.py`](repro/vivo_ab.py)

## Result

Two task families, ten membership questions each, both arms:

| Task family | Arm | Answer accuracy | Target present in context |
|---|---|---:|---:|
| grep membership | off | 6/10 | 20% |
| grep membership | on | 6/10 | 20% |
| file-listing membership | off | 6/10 | 10% |
| file-listing membership | on | 6/10 | 10% |

**Identical, question by question.** The extension changed nothing in vivo.

An earlier single-shot run appeared to flip one answer from "No" to "Yes". It did not reproduce
across ten targets and should be treated as **noise**, not evidence.

## Why: the scalar-array path is almost never reached

Transforms actually applied (file-listing run, both arms identical):

```
router:noop            x11
router:text:0.94        x5
router:text:0.91/0.92   x3
router:smart_crusher    x1     <- the only invocation of the JSON path
```

Real agent tool output *is* array-shaped — grep returned 240, 480, and 1833 element scalar arrays.
But Headroom's content router classifies nearly all of it as **text** and sends it to `TextCrusher`,
not to the JSON scalar-array crusher that [improvement-01](improvement-01-query-aware-retention.md)
modifies. This is deliberate, not accidental: the Rust suite contains a test named

> `transforms::detection::tests::grep_search_results_route_to_plain_text_per_locked_design`

## Three independent layers keep query-conditioning from mattering

Each measured separately:

1. **Mode.** `headroom proxy` defaults to `--mode cache`. Compression is gated on
   `is_token_mode(self.config.mode)` ([`openai.py:3442`](../headroom/proxy/handlers/openai.py)), so
   in the default configuration **no compression runs at all**. Measured: a 34,371-token request
   with a 1833-element array and zero cache benefit produced `transforms_applied: []`.
2. **Routing.** In token mode, agent tool output is classified as text and bypasses the
   query-aware JSON path — by locked design (above).
3. **Caching.** When compression does run, the result cache is keyed on content only
   ([result-04](result-04-cache-defeats-query-conditioning.md)), so a repeated tool output replays
   the first question's compression.

## What this does and does not overturn

**Stands.** The synthetic result is unaffected: on JSON scalar arrays the extension raises interior
retention from 28% to 100% at lower token cost ([result-05](result-05-extension-effect.md)). That
measurement was taken on the Anthropic `/v1/messages` path where the scalar crusher genuinely runs.

**Bounded.** The extension's practical reach is narrower than the synthetic benchmark implies. It
applies to tool outputs the router classifies as JSON arrays of scalars — not to grep, log, or
listing output shaped as text, which is the bulk of what this agent produced.

**Not shown.** That *no* real agent hits the path. One agent, one model, one repo, two task
families. An agent whose tools return structured JSON (API clients, database queries, CI result
objects) may well hit it. Untested.

## Honest reading

The interesting finding is no longer "relevance ranking improves retention". It is that **Headroom
ships query-conditioned compression that the default agent path cannot reach**, for three separate
and independently verified reasons. The extension is a working demonstration of what the JSON path
would gain if it were reached — and the measurement of *why it is not reached* is the more useful
contribution.
