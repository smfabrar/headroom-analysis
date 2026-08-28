import json, urllib.request, os, random, string, sys
CAP=os.environ["CAP"]; PORT=os.environ["PORT"]; NT=int(sys.argv[1])
random.seed(77)
W=[''.join(random.choices(string.ascii_lowercase,k=8)) for _ in range(4000)]
def payload(t): return json.dumps([{"c":t,"id":j,"body":" ".join(random.choices(W,k=60))} for j in range(60)])
msgs=[]; last_len=0
for t in range(NT):
    p=payload(t); last_len=len(p)
    msgs += [{"role":"user","content":f"step {t}"},
             {"role":"assistant","content":[{"type":"tool_use","id":f"tu{t}","name":"q","input":{}}]},
             {"role":"user","content":[{"type":"tool_result","tool_use_id":f"tu{t}","content":p},
                                       {"type":"text","text":"go"}]}]
body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,"messages":msgs}
req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",data=json.dumps(body).encode(),
    headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
urllib.request.urlopen(req,timeout=90).read()
fwd=json.loads(json.loads(open(CAP).read().strip().split("\n")[-1])["body"])
last=None
for m in fwd["messages"]:
    if isinstance(m.get("content"),list):
        for b in m["content"]:
            if b.get("type")=="tool_result": last=b["content"]
s=last if isinstance(last,str) else json.dumps(last)
pct=(1-len(s)/last_len)*100
print(f"  FIRST request to fresh proxy, {len(msgs)} messages ({NT} turns): newest {pct:5.1f}% saved  {'COMPRESSED' if pct>10 else '*** NOT ***'}")
