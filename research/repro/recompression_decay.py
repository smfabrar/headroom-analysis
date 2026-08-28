"""Repeated re-compression of an unchanged tool output.

One tool result enters the conversation once. Each subsequent turn asks a new
question and adds NO new information. Measures how the retained set evolves.
"""
import json, os, urllib.request, time

PORT=os.environ.get("PORT","8905"); CAP=os.environ["CAPTURE"]
N=int(os.environ.get("N","300")); TURNS=int(os.environ.get("TURNS","20"))
ITEMS=[f"INV-2026-{i:04d}" for i in range(1,N+1)]
SALT=f"decay{time.time_ns():019d}"
# Stable system-prompt bulk. Real agents carry multi-KB system prompts; the
# prompt cache needs >= PrefixTracker.min_cached_tokens (1024) of confirmed
# cached tokens before `get_frozen_message_count()` returns anything but 0.
# Without this the provider-confirmed tracker is pinned at 0 for rig reasons
# rather than for the reason under test.
SYSPAD=int(os.environ.get("SYSPAD","0"))
PAD=("You are a meticulous invoicing assistant. Follow the operator handbook. "*max(1,SYSPAD//76))[:SYSPAD]

def tr(body):
    d=json.loads(body); out=None
    for m in d.get("messages",[]):
        c=m.get("content")
        if isinstance(c,list):
            for b in c:
                if isinstance(b,dict) and b.get("type")=="tool_result":
                    v=b.get("content"); out=v if isinstance(v,str) else json.dumps(v)
    return out or ""

msgs=[{"role":"user","content":"List the invoices."},
      {"role":"assistant","content":[{"type":"tool_use","id":"t","name":"list_invoices","input":{}}]},
      {"role":"user","content":[{"type":"tool_result","tool_use_id":"t","content":json.dumps(ITEMS)},
                                {"type":"text","text":"List the invoices."}]}]
print(f"N={N}  turns={TURNS}")
print(f"{'turn':>4} {'items kept':>11} {'delta':>6} {'tool_result bytes':>18}")
print("-"*45)
prev=None
rows=[]
for t in range(1,TURNS+1):
    if t>1:
        msgs.append({"role":"assistant","content":"Noted."})
        msgs.append({"role":"user","content":f"Question {t}: how many invoices are listed?"})
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,
          "system":f"Session {SALT}. {PAD}","messages":msgs}
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-api-key":"t",
                 "anthropic-version":"2023-06-01"})
    urllib.request.urlopen(req,timeout=120).read()
    rec=None
    for line in open(CAP).read().strip().split("\n"):
        if line and f"Session {SALT}." in line: rec=json.loads(line)
    out=tr(rec["body"]); kept=[x for x in ITEMS if x in out]
    d="" if prev is None else f"{len(kept)-prev:+d}"
    print(f"{t:>4} {len(kept):>11} {d:>6} {len(out):>18}")
    rows.append(dict(turn=t,kept=len(kept),bytes=len(out)))
    prev=len(kept)
json.dump(rows,open("research/data/recompression_decay.json","w"),indent=2)
first,last=rows[0]["kept"],rows[-1]["kept"]
print(f"\nretained {first} -> {last} over {TURNS} turns "
      f"({(first-last)/max(1,first):.0%} of the survivors lost to re-compression alone)")
