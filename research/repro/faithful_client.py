"""Does the multi-turn decay survive a client that behaves like a REAL one?

Variables tested (things my first synthetic client omitted):
  V1 baseline          : no cache_control, no beta headers      (original test)
  V2 cache_control     : client places cache_control like Claude Code does
  V3 + beta headers    : anthropic-beta prompt-caching header
  V4 + system prompt   : realistic system block
"""
import json, urllib.request, os, random, string
CAP=os.environ["CAP"]; PORT="8820"
random.seed(101)
W=[''.join(random.choices(string.ascii_lowercase,k=8)) for _ in range(4000)]
def payload(t): return json.dumps([{"c":t,"id":j,"body":" ".join(random.choices(W,k=60))} for j in range(60)])

def send(msgs, cache_control=False, beta=False, system=False):
    m=json.loads(json.dumps(msgs))
    if cache_control:
        # real clients mark the last content block of the last message
        last=m[-1]
        if isinstance(last.get("content"),list):
            last["content"][-1]["cache_control"]={"type":"ephemeral"}
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,"messages":m}
    if system:
        body["system"]=[{"type":"text","text":"You are Claude Code, an agentic coding tool.",
                         **({"cache_control":{"type":"ephemeral"}} if cache_control else {})}]
    h={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"}
    if beta: h["anthropic-beta"]="prompt-caching-2024-07-31"
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",data=json.dumps(body).encode(),headers=h)
    urllib.request.urlopen(req,timeout=90).read()
    return json.loads(json.loads(open(CAP).read().strip().split("\n")[-1])["body"])

def newest_pct(fwd, n):
    last=None
    for m in fwd["messages"]:
        if isinstance(m.get("content"),list):
            for b in m["content"]:
                if b.get("type")=="tool_result": last=b["content"]
    s=last if isinstance(last,str) else json.dumps(last)
    return (1-len(s)/n)*100

def variant(name, **kw):
    msgs=[]; out=[]
    for t in range(4):
        p=payload(f"{name}{t}")
        msgs += [{"role":"user","content":f"step {t}"},
                 {"role":"assistant","content":[{"type":"tool_use","id":f"tu{t}","name":"q","input":{}}]},
                 {"role":"user","content":[{"type":"tool_result","tool_use_id":f"tu{t}","content":p},
                                           {"type":"text","text":"go"}]}]
        out.append(newest_pct(send(msgs, **kw), len(p)))
    print(f"{name:<34}" + "".join(f"{v:8.1f}%" for v in out))

print(f"{'variant':<34}{'turn0':>9}{'turn1':>9}{'turn2':>9}{'turn3':>9}")
variant("V1 baseline (as before)")
variant("V2 + client cache_control", cache_control=True)
variant("V3 + cache_control + beta hdr", cache_control=True, beta=True)
variant("V4 + all + system prompt", cache_control=True, beta=True, system=True)
