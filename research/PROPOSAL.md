# Proposal — Query-Conditioned Retention for Scalar Arrays

**Status:** committed direction · **Gating step:** real-agent traffic capture (not yet run)
**Supersedes:** the CCR-retention plan in `~/.claude/plans/i-have-been-given-soft-nova.md`

---

## Abstract

Headroom is a proxy that compresses LLM context in flight. For arrays of **objects** it ranks
items by relevance to the user's question. For arrays of **scalars** — strings, numbers — it does
not: the query is extracted from the request, threaded through the pipeline, and then dropped at
the final step. Selection falls back to head / stride / tail sampling. The probability that the
item the user actually asked about survives compression is therefore `K/N` — chance.

We verified this two independent ways. At source level, `crush_string_array` accepts no query
parameter. Empirically, four different questions over the same 60-item array produce a
**byte-identical** retained set.

We propose routing scalar arrays through the BM25/hybrid relevance scorer that already exists in
`headroom/relevance/` but is unused on this path, at an **unchanged token budget**.

We evaluate on two layers: a deterministic harness measuring retention rate and token cost across
array size, target position, and content type; and live coding-agent runs measuring whether
improved retention changes task outcomes.

The interesting result is **not** that relevance helps needle-retrieval — that is near-tautological.
It is the **trade-off frontier** between targeted retention and representative sampling, measured
against control tasks where relevance is the wrong selection criterion.

---

## Research method

1. **Ground truth is the forwarded bytes.** Every claim about "what the model sees" is captured
   from a fake upstream that records the exact body Headroom forwards. Library-level results are
   indicative only — the library and proxy paths were observed to make different decisions on
   identical input.

2. **Mechanism before measurement.** The gap is established at source level first, so the
   measurement is confirming a known mechanism rather than fishing for an effect.

3. **The harness is built before the implementation.** This is deliberate pre-registration: the
   baseline curve is measured against unmodified Headroom, so the implementation cannot be tuned
   to flatter the benchmark.

4. **Two evaluation layers, reported separately.**
   - *Deterministic:* retention rate and token cost. No LLM, no API key, zero variance,
     exactly reproducible by a reviewer.
   - *In-vivo:* a real coding agent on benchmark tasks. Noisy, small-N, reported with explicit
     caveats and never used to carry the headline claim.

5. **Controls are half the experiment, not a caveat.** Tasks where relevance is the wrong criterion
   ("how many items are there?", "list the first ten", "what is the distribution?") must show
   **no regression**. Plus: empty/vague queries must fall back gracefully, and diversity loss must
   be measured rather than assumed.

6. **Both arms from one build.** The extension is env-gated and default-off, so the baseline is
   byte-identical to upstream and the only variable is the flag.

7. **Negative results are recorded, not discarded.** `research/` already contains two rejected
   candidates and one downgraded finding. The same standard applies here.

---

## Why this idea and not the others

| Requirement from `task.md` | How this satisfies it |
|---|---|
| "identify a gap or a potentially useful new feature" | A capability that does not exist, not a defect — survives the "is this just a bug fix?" objection |
| "implement a proof of concept" | Small and honest: connect infrastructure that already ships but is unwired on this path |
| "quantitatively measure the effect" | Headline metric is deterministic; effect size is large and predicted a priori (`K/N` → ~100%) |
| "select a coding agent and benchmark tasks" | Second evaluation layer, with real agent traffic |
| graded on "what remains uncertain" | The tautology risk and the diversity trade-off are stated up front and measured |

Candidates 03–06 were investigated and are recorded as parked, downgraded, or rejected.
Candidate 02 (compression stops after the first turn) is a **defect fix**, not an extension; it is
reported as a secondary observation with its unvalidated status stated plainly.
[Finding 01](finding-01-unrecoverable-scalar-arrays.md) is not a separate deliverable — it is the
motivation for this work: because dropped scalars are unrecoverable, the selection has to be right.

---

## Kill criteria

Stated in advance so the answer is not rationalised after the fact.

- **Real agent traffic never exercises the scalar-array path.** Then the extension is unmeasurable
  in-vivo. Reframe honestly, report the deterministic result plus the traffic-shape evidence for
  why it does not fire, and say so.
- **Relevance selection regresses the control tasks.** Then the finding becomes the trade-off
  itself, not the improvement — still publishable, different narrative.
- **Real queries are too vague for BM25 to separate items.** Then the measured fallback rate is the
  result.

## Open risk

The gating unknown is what shapes real coding-agent tool outputs actually have. Real traffic is
mostly file reads, diffs, and shell output, which route to TextCrusher / DiffCompressor /
LogCompressor. Flat scalar arrays may be rarer than the synthetic tests assume. **This is checked
before any implementation begins.**

---

## KILL CRITERION FIRED (see [result-06](result-06-in-vivo-null.md))

> "**Real agent traffic never exercises the scalar-array path.** Then the extension is unmeasurable
> in-vivo. Reframe honestly, report the deterministic result plus the traffic-shape evidence for why
> it does not fire, and say so."

This is what happened. Measured: a real function-calling agent produces large scalar arrays, but
Headroom routes them to `TextCrusher` by locked design, so the modified path fires roughly once in
twenty compressions and the A/B is a null result (6/10 vs 6/10, identical per question).

The submission's contribution is therefore reframed, per the plan written in advance:
the extension stands as a **measured demonstration on the path where the crusher runs**
([result-05](result-05-extension-effect.md)), and the primary finding becomes the **three
independent layers** that prevent Headroom's query-conditioned compression from being reachable in
the default agent path.
