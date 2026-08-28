# Result 04 — The compressed-result cache is keyed on content, not on the query

**Status:** verified on unmodified Headroom (gate off) and via runtime trace
**Repro:** [`repro/cache_defeats_relevance.py`](repro/cache_defeats_relevance.py)

## The mechanism

[`headroom/transforms/content_router.py:5273`](../headroom/transforms/content_router.py):

```python
content_key = hash((content, getattr(self, "_runtime_target_ratio", None)))
```

The compressed-result cache key is **(content, target_ratio)**. The user's query is not part of
it. When the same tool output recurs with a different question, the router returns the compression
computed for the *first* question.

## How it surfaced

While evaluating query-aware retention, a 35-request sweep over the same five invoice arrays
produced only **5** calls into the selection function — one per distinct array — and every trace
carried the **first** cell's query:

```
[QA] n=400  pins=[0,1,2,3,4]  query="Is INV-2026-0001 in the list? ..."
[QA] n=1000 pins=[0,1,2,3,4]  query="Is INV-2026-0001 in the list? ..."
```

Positions 100, 200, 250, 500 were never compressed with their own question. They replayed the
compression built for `INV-2026-0001`.

Direct confirmation on **unmodified** Headroom, dict arrays — the path Headroom documents as
relevance-ranked — two different questions over identical content:

```
identical output for two different questions? True
after changing content (new cache key), output differs?  True
```

Byte-identical output for two different questions; perturbing one item changes the key and the
output changes. The cache, not the compressor, decided what the model saw.

## Why it matters beyond this project's extension

Headroom already applies **query-conditioned relevance ranking to dict arrays**
(`planning.rs`: query anchors, BM25 `score_batch`, `relevance_threshold`, `preserve_fields`). That
feature is silently bypassed whenever the same tool output recurs with a different question — which
is the normal shape of agent work: re-running the same `grep`, `ls`, or test command across turns
and asking something different about it each time.

The first question of a session therefore determines the compression every later question receives,
for as long as the content is unchanged and the entry is cached.

## Scope of the claim — what is and is not shown

- **Shown:** the cache key omits the query; identical content + different question returns
  byte-identical compressed output; the trace proves the compressor ran once with the first query.
- **Shown:** on the **scalar** path this causes measurable loss — queried items were dropped that
  would otherwise have been retained ([result-05](result-05-extension-effect.md)).
- **Not shown:** harm on the **dict** path. The 300-item dict array in the probe was compacted
  **losslessly** (`0/300` items dropped), so nothing was lost even though the query was ignored.
  Demonstrating dict-path harm needs a dict array large or heterogeneous enough to force lossy
  row-dropping. **Untested.**

## Consequence for the evaluation

Any benchmark that reuses identical tool-output content across cells silently measures **cache
replay**, not compression. The harness now appends a cell-unique sentinel item so every cell gets
its own cache key. [result-03](result-03-baseline-retention.md) carries a correction for this.
