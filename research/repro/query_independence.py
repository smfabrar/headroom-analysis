"""Does the user's question influence WHICH items survive compression?"""
import json, urllib.request, os
CAP=os.environ["CAP"]; PORT="8840"
def probe(question, items):
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,"messages":[
      {"role":"user","content":question},
      {"role":"assistant","content":[{"type":"tool_use","id":"t","name":"q","input":{}}]},
      {"role":"user","content":[{"type":"tool_result","tool_use_id":"t","content":json.dumps(items)},
                                {"type":"text","text":question}]}]}
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
    urllib.request.urlopen(req,timeout=60).read()
    d=json.loads(json.loads(open(CAP).read().strip().split("\n")[-1])["body"])
    tr=None
    for m in d["messages"]:
        if isinstance(m.get("content"),list):
            for b in m["content"]:
                if b.get("type")=="tool_result": tr=b["content"]
    return tr if isinstance(tr,str) else json.dumps(tr)

items=[f"INV-2026-{i:04d}" for i in range(1,61)]
targets=["INV-2026-0021","INV-2026-0044","INV-2026-0009","INV-2026-0055"]
kept_sets=[]
for tgt in targets:
    out=probe(f"Is {tgt} in the list? Report its status.", items)
    kept=[i for i in items if i in out]
    kept_sets.append(tuple(kept))
    print(f"asked about {tgt}: survived={len(kept)}  target_kept={tgt in out}")
print()
print(f"kept set identical across all 4 different questions? {len(set(kept_sets))==1}")
print(f"kept items: {list(kept_sets[0])}")
