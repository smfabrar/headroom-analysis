"""Does re-compression decay affect compressors other than crush_string_array?

Same protocol as recompression_decay.py, but the tool output is shaped to route
to the TEXT path (grep-style lines), which is what real agent traffic produces.
"""
import json, os, urllib.request, time
PORT=os.environ.get("PORT","8906"); CAP=os.environ["CAPTURE"]
TURNS=int(os.environ.get("TURNS","10")); KIND=os.environ.get("KIND","grep")
N=int(os.environ.get("N","300"))

if KIND=="grep":
    payload="\n".join(f"src/{['auth','billing','session','worker'][i%4]}/mod_{i:03d}.py:{10+i%40}:"
                      f"    log.warning('retry %d for item {i}', attempt)" for i in range(N))
elif KIND=="prose":
    payload="\n".join(f"Paragraph {i}. The subsystem handles case {i} by validating the payload "
                      f"and retrying up to three times before escalating to the operator queue."
                      for i in range(N))
else:
    payload=json.dumps([f"INV-2026-{i:04d}" for i in range(1,N+1)])

SALT=f"gen{KIND}{time.time_ns():019d}"
def tr(body):
    d=json.loads(body); out=None
    for m in d.get("messages",[]):
        c=m.get("content")
        if isinstance(c,list):
            for b in c:
                if isinstance(b,dict) and b.get("type")=="tool_result":
                    v=b.get("content"); out=v if isinstance(v,str) else json.dumps(v)
    return out or ""

msgs=[{"role":"user","content":"Show me the search results."},
      {"role":"assistant","content":[{"type":"tool_use","id":"t","name":"search","input":{}}]},
      {"role":"user","content":[{"type":"tool_result","tool_use_id":"t","content":payload},
                                {"type":"text","text":"Show me the search results."}]}]
print(f"KIND={KIND}  payload={len(payload)} chars  turns={TURNS}")
print(f"{'turn':>4} {'bytes':>8} {'lines':>7} {'delta bytes':>12}")
print("-"*36)
prev=None
for t in range(1,TURNS+1):
    if t>1:
        msgs.append({"role":"assistant","content":"Noted."})
        msgs.append({"role":"user","content":f"Question {t}: summarise what you see."})
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,
          "system":f"Session {SALT}.","messages":msgs}
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
    urllib.request.urlopen(req,timeout=120).read()
    rec=None
    for line in open(CAP).read().strip().split("\n"):
        if line and f"Session {SALT}." in line: rec=json.loads(line)
    out=tr(rec["body"])
    d="" if prev is None else f"{len(out)-prev:+d}"
    print(f"{t:>4} {len(out):>8} {out.count(chr(10))+1:>7} {d:>12}")
    prev=len(out)
