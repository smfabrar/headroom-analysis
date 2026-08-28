"""Does the content-keyed result cache defeat Headroom's OWN dict-array
relevance ranking?

Unmodified Headroom (gate off). Same DICT array, two different questions,
separate conversations. Dict arrays are the path Headroom documents as
query-ranked. If the second question returns the first question's items
byte-for-byte, the cache has overridden relevance ranking.
"""
import json, os, urllib.request, time
CAP=os.environ["CAPTURE"]; PORT=os.environ.get("PORT","8860")
def ask(items, q, salt):
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,"system":f"Session {salt}.",
     "messages":[{"role":"user","content":q},
      {"role":"assistant","content":[{"type":"tool_use","id":"t","name":"q","input":{}}]},
      {"role":"user","content":[{"type":"tool_result","tool_use_id":"t","content":json.dumps(items)},
                                {"type":"text","text":q}]}]}
    r=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",
      data=json.dumps(body).encode(),
      headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
    urllib.request.urlopen(r,timeout=90).read()
    rec=None
    for line in open(CAP).read().strip().split("\n"):
        if f"Session {salt}." in line: rec=json.loads(line)
    d=json.loads(rec["body"])
    for m in d["messages"]:
        if isinstance(m.get("content"),list):
            for b in m["content"]:
                if isinstance(b,dict) and b.get("type")=="tool_result":
                    v=b["content"]; return v if isinstance(v,str) else json.dumps(v)

# dict array: the path Headroom DOES rank by relevance
items=[{"id":f"TCK-{i:04d}","status":["open","closed","pending"][i%3],
        "owner":f"user{i%17}","summary":f"ticket about subsystem {i%23} handling case {i}"}
       for i in range(300)]
qA="What is the status of ticket TCK-0007?"
qB="What is the status of ticket TCK-0242?"

outA=ask(items,qA,f"dictA-{time.time_ns():019d}")
outB=ask(items,qB,f"dictB-{time.time_ns():019d}")
print(f"identical output for two different questions? {outA==outB}")
print(f"TCK-0007 in A: {'TCK-0007' in outA}   in B: {'TCK-0007' in outB}")
print(f"TCK-0242 in A: {'TCK-0242' in outA}   in B: {'TCK-0242' in outB}")

# control: same questions, but content differs by one item -> different cache key
items2=items[:-1]+[{"id":"TCK-9999","status":"open","owner":"z","summary":"sentinel"}]
outC=ask(items2,qB,f"dictC-{time.time_ns():019d}")
print(f"\nafter changing content (new cache key), B-query output differs from A? {outC!=outA}")
print(f"TCK-0242 in C: {'TCK-0242' in outC}")

# ---- harm demonstration: ask about an item the CACHED output dropped ----
print("\n=== HARM DEMO ===")
dropped=[it["id"] for it in items if it["id"] not in outA]
print(f"items dropped from the cached compression: {len(dropped)}/{len(items)}")
victim=dropped[len(dropped)//2]
qV=f"What is the status of ticket {victim}? Who owns it?"
outV=ask(items,qV,f"dictV-{time.time_ns():019d}")
print(f"asking specifically about {victim}")
print(f"  output identical to the cached one? {outV==outA}")
print(f"  {victim} present in what the model receives? {victim in outV}")

# same question, content perturbed so the cache key changes
outW=ask(items2,qV,f"dictW-{time.time_ns():019d}")
print(f"\nsame question, cache bypassed (content perturbed):")
print(f"  {victim} present? {victim in outW}")
