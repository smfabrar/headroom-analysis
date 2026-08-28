# Research log — candidate findings

Goal: find the **strongest** defensible empirical claim about Headroom, then build the
extension that follows from it. We explore several candidates, score them, and commit
to one. Everything here is evidence for `ANALYSIS.md`.

## Scoring criteria

| Criterion | Why it matters |
|---|---|
| **Rigor** | Can it be measured deterministically, without LLM noise? |
| **Impact** | Does it affect the project's headline claim, or a corner case? |
| **Novelty** | Is it already known upstream (issues, CHANGELOG, REALIGNMENT docs)? |
| **Extension fit** | Does a *designed* extension follow, or only a patch? |
| **Cost** | API spend and days to evaluate properly. |

## Improvements (capability extensions, not defects)

| # | Proposal | Status | Measurable? | Reproducible? |
|---|---|---|---|---|
| I-01 | [Query-aware retention for scalar arrays](improvement-01-query-aware-retention.md) | **premise verified at source + empirically**; mechanism feasibility tested ([result-01](result-01-bm25-scalar-feasibility.md)) | yes — retention rate vs. token cost, Pareto curve | yes — deterministic, no API key for the headline metric |

## Results

| # | Test | Outcome |
|---|---|---|
| R-11 | [Real Claude agent, live Anthropic API, real cache lapses](result-11-in-vivo-anthropic.md) | **Mechanism confirmed in vivo, severity refuted.** Baseline loses 19.1% of forwarded tool output on the first real cache miss (17213->13930); fixed arm holds flat. But the **ratchet does NOT reproduce**: 4 genuine misses, only the first cost anything. 300/300 lines survived, 7/7 answers correct in BOTH arms — no agent harm demonstrated. Tempers R-07/R-09/R-10. |
| R-10 | [Multi-turn cross-handler property sweep](result-10-property-sweep.md) | **HEADLINE.** A harness for properties Headroom's suite cannot express (idempotence, cross-handler equivalence, turn-index independence). 72 cells x 3 repeats = 216 cell-runs. **5 stable violations, all `anthropic`+`baseline`; the fixed arm has zero violations and zero flaky cells.** Decay is NOT scalar-array-specific: `log_lines` loses 79%, `search_results` 41% of bytes. Also finds baseline Anthropic compression is **nondeterministic** (4 flaky cells). |
| R-09 | [Why Anthropic-only: `min` vs assignment](result-09-why-anthropic-only.md) | **Mechanism measured.** OpenAI assigns `compute_frozen_count`; Anthropic clamps it with `min(tracker, compute)`. Cold cache -> `tracker=0` -> `final=0` -> whole conversation live -> already-compressed tool_result compressed again. **Corrects R-07/R-08:** the earlier cache-warm control was invalid (below the 1024-token threshold). Decay is conditional on cache misses — **one item lost per miss, never recovered**. Fix holds flat. |
| R-08 | [Idempotence fix + scope](result-08-idempotence-fix.md) | Root cause: the existing `_is_already_compressed` guard detects compressed content only by CCR marker, and scalar arrays carry none. Hash-based guard holds 241 bytes flat vs 241->129. **Anthropic-path only** — OpenAI path with identical payload does not decay; real-agent (gpt-4o-mini, OpenAI path) A/B is correctly null. |
| R-07 | [Compounding re-compression decay](result-07-recompression-decay.md) | **HEADLINE.** An unchanged tool output shrinks 15->8 items over 8 turns (−1/turn), adding no information. Compressed content is substituted back and re-compressed. Floor at 8 = the `n<=8` passthrough guard. Verified on unmodified Headroom. |
| R-06 | [In vivo the extension has no effect](result-06-in-vivo-null.md) | **NULL RESULT.** Both arms 6/10, identical per question. Agent tool output routes to TextCrusher, not the JSON scalar path (locked design). Three layers block query-conditioning: default cache mode, text routing, content-keyed cache. |
| R-05 | [Effect of query-aware scalar retention](result-05-extension-effect.md) | **Interior retention 28% -> 100% (+72pp), token cost -4.3%, controls flat.** Two implementation errors found by measurement. |
| R-04 | [Cache is keyed on content, not query](result-04-cache-defeats-query-conditioning.md) | **`content_key = hash((content, target_ratio))` — query omitted. Same content + different question replays the first question's compression.** Also bypasses Headroom's existing dict-array relevance ranking. |
| R-03 | [Baseline query-conditioned retention](result-03-baseline-retention.md) | **Interior retention 28%; collapses to 0% at N=400. Head/tail 100%. 89.7% byte saving. Query has zero influence.** 250 cells, $0, 190s. |
| R-02 | [What Headroom's own eval suite measures](result-02-existing-eval-suite.md) | Accuracy-*preservation* suite, single-turn only, agent category N=8, default model gpt-4o-mini. Explains why finding-02 was never caught. Phase B should extend `BeforeAfterRunner`, not replace it. |
| R-01 | [Can BM25 separate items in a scalar array?](result-01-bm25-scalar-feasibility.md) | **Yes for exact-mention queries (35/35, median rank 1). Zero signal for descriptive queries — all scores 0.0.** Sharp, detectable boundary; fallback trigger is free. |

## Candidates (defects)

| # | Candidate | Status | Rigor | Impact | Extension fit | Verdict |
|---|---|---|---|---|---|---|
| 01 | [Scalar arrays discarded with no recovery path](finding-01-unrecoverable-scalar-arrays.md) | **verified (synthetic)** | high — deterministic, no API key | contradicts "nothing is ever thrown away", but sampling IS documented in `limitations.mdx` | needs reframing to a recoverability contract, else a 20-line patch | solid, novelty medium |
| 02 | [Compression fires once per conversation, then stops](finding-02-multiturn-compression-stops.md) | **reproducible, mechanism IDENTIFIED, client-realism confound eliminated** | high — deterministic, no API key | attacks the headline coding-agent savings claim directly | fix + a multi-turn regression harness the project lacks | **strongest so far**, blocked on real-agent validation |
| 03 | [Savings accounting inconsistencies](finding-03-savings-accounting.md) | **observed, not claimed** | needs code-level derivation | potentially high (published figures) | — | park until 02 is settled; has a defensible counter-reading |
| 04 | Net cost on multi-turn workloads once cache effects are priced in | not started | — | — | — | partially subsumed by 02 |
| 05 | CCR retention: markers outliving originals (FIFO cap + 30-min TTL) | superseded by 01 | — | — | — | parked |
| 04 | [CCR retrieval has no conversation scoping](finding-04-ccr-no-conversation-scoping.md) | **mechanism verified, severity DOWNGRADED** | high | negligible: no accidental path, attacker gains nothing over shell access, content-derived hashes imply dedup is intentional | — | **rejected as a candidate** |
| 06 | Tool-array flip busting the prompt cache (REALIGNMENT P2-26) | **tested — negative** | high | none observed: tools array stayed byte-stable across turns | — | closed, no defect found |

## Current ranking

**02 is the front-runner.** It attacks the headline value proposition (savings on coding agents) rather
than a documented corner case, and it explains why the project's own single-turn benchmarks would
not catch it. Both are deterministic and free to verify. 02 is blocked on real-agent validation —
if a real client's session keying makes the behaviour disappear, 01 becomes the fallback.

04 was investigated and **rejected**: no accidental path exists, a prompt-injected agent with shell
access gains nothing from it, and the content-derived hash key suggests the absence of scoping is
deliberate deduplication rather than an oversight. Recorded as a negative result.

**02 remains the front-runner** on impact; 01 is the fallback. Neither has been validated against a
real coding agent yet, which is still the gating step.

Do **not** commit until a real coding agent has been run through the proxy.

## Method notes

- **Ground truth = forwarded bytes.** All claims about "what the model sees" are captured with
  `repro/fake_upstream.py`, a fake Anthropic endpoint that records the exact body Headroom
  forwards. Library-level results are treated as indicative only, because the library and
  proxy paths were observed to make *different* decisions on identical input.
- **Measure the tool_result, not the whole body.** An early error searched the entire request,
  which is contaminated by the user's question text. Corrected in `repro/scalar_array_loss.py`.
- Synthetic payloads establish mechanism; real captured agent traffic is required before any
  claim about practical impact.

## Open cross-cutting questions

- [ ] What does upstream already know? (git log, GitHub issues, `REALIGNMENT/01-bug-list.md`)
- [ ] What shapes do real coding-agent tool outputs actually have?
- [ ] Do the OpenAI Chat/Responses paths behave like the Anthropic path?
