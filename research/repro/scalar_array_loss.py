import json, re, urllib.request, os
CAP=os.environ["CAP"]

def probe(items, question="anything unusual?"):
    payload=json.dumps(items)
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,
      "messages":[{"role":"user","content":"run the query"},
        {"role":"assistant","content":[{"type":"tool_use","id":"tu1","name":"q","input":{}}]},
        {"role":"user","content":[{"type":"tool_result","tool_use_id":"tu1","content":payload},
                                  {"type":"text","text":question}]}]}
    req=urllib.request.Request("http://127.0.0.1:8792/v1/messages",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
    urllib.request.urlopen(req,timeout=90).read()
    d=json.loads(json.loads(open(CAP).read().strip().split("\n")[-1])["body"])
    # extract ONLY the tool_result content the model receives
    tr=None
    for m in d["messages"]:
        if isinstance(m["content"],list):
            for blk in m["content"]:
                if blk.get("type")=="tool_result": tr=blk["content"]
    tr = tr if isinstance(tr,str) else json.dumps(tr)
    has_tool = any(t.get("name")=="headroom_retrieve" for t in d.get("tools",[]))
    return tr, has_tool

print(f"{'array (n items)':<26}{'kept':>6}{'lost':>7}   {'marker in tool_result':<22}{'tool':>6}  can recover?")
for n in (20, 40, 100, 300):
    items=[f"INV-2026-{i:04d}" for i in range(1,n+1)]
    tr, has_tool = probe(items)
    kept=sum(1 for s in items if s in tr)
    marker = ("<<ccr:" in tr) or ("hash=" in tr) or ("Retrieve" in tr)
    lost=n-kept
    rec = "n/a (nothing lost)" if lost==0 else ("YES" if marker else "NO — unreachable")
    print(f"{'string IDs x'+str(n):<26}{kept:>6}{lost:>7}   {str(marker):<22}{str(has_tool):>6}  {rec}")

# dict rows for contrast
rows=[{"invoice":f"INV-2026-{i:04d}","amount":100+i,"status":"unpaid"} for i in range(1,41)]
tr,has_tool=probe(rows)
kept=sum(1 for r in rows if r["invoice"] in tr)
marker=("<<ccr:" in tr) or ("hash=" in tr) or ("Retrieve" in tr)
print(f"{'dict rows x40 (contrast)':<26}{kept:>6}{40-kept:>7}   {str(marker):<22}{str(has_tool):>6}  {'n/a (nothing lost)' if kept==40 else ('YES' if marker else 'NO')}")
print("\n--- what the model literally sees for dict rows x40 ---")
print(tr[:300])
