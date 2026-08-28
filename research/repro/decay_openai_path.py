"""Same decay protocol, OpenAI /v1/chat/completions shape.

Isolates whether the re-compression decay is a property of the payload
(JSON scalar array) or of the Anthropic handler.
"""
import json, os, urllib.request, time
PORT=os.environ.get("PORT","8930"); CAP=os.environ["CAPTURE"]
N=int(os.environ.get("N","300")); TURNS=int(os.environ.get("TURNS","10"))
ITEMS=[f"INV-2026-{i:04d}" for i in range(1,N+1)]
SALT=f"oa{time.time_ns():019d}"

def fwd_tool(salt):
    rec=None
    for line in open(CAP).read().strip().split("\n"):
        if line and salt in line: rec=json.loads(line)
    if not rec: return ""
    d=json.loads(rec["body"])
    for m in d.get("messages",[]):
        if m.get("role")=="tool":
            c=m.get("content"); return c if isinstance(c,str) else json.dumps(c)
    return ""

msgs=[{"role":"system","content":f"Marker {SALT}."},
      {"role":"user","content":"List the invoices."},
      {"role":"assistant","content":None,"tool_calls":[{"id":"c1","type":"function",
        "function":{"name":"list_invoices","arguments":"{}"}}]},
      {"role":"tool","tool_call_id":"c1","content":json.dumps(ITEMS)}]
print(f"OpenAI path  N={N}  turns={TURNS}")
print(f"{'turn':>4} {'items kept':>11} {'delta':>6} {'bytes':>8}")
print("-"*34)
prev=None
for t in range(1,TURNS+1):
    if t>1:
        msgs.append({"role":"assistant","content":"Noted."})
        msgs.append({"role":"user","content":f"Question {t}: how many invoices are listed?"})
    body={"model":"gpt-4o-mini","messages":msgs,"max_tokens":16}
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer test"})
    try: urllib.request.urlopen(req,timeout=120).read()
    except Exception as e: print("  err",e); break
    out=fwd_tool(SALT); kept=[x for x in ITEMS if x in out]
    d="" if prev is None else f"{len(kept)-prev:+d}"
    print(f"{t:>4} {len(kept):>11} {d:>6} {len(out):>8}")
    prev=len(kept)
