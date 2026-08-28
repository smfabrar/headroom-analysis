"""Which tool_result gets compressed: the newest (documented) or the older ones?"""
import json, urllib.request, os, random, string
CAP=os.environ["CAP"]
random.seed(21)
W=[''.join(random.choices(string.ascii_lowercase,k=8)) for _ in range(4000)]
def payload(tag):
    # tag embedded in every row so we can identify which turn a block came from
    return json.dumps([{"turn":tag,"id":j,"body":" ".join(random.choices(W,k=60))} for j in range(60)])

def send(messages):
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,"messages":messages}
    req=urllib.request.Request("http://127.0.0.1:8792/v1/messages",data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
    urllib.request.urlopen(req,timeout=90).read()
    return json.loads(json.loads(open(CAP).read().strip().split("\n")[-1])["body"])

msgs=[]; sent={}
for turn in range(4):
    p=payload(f"T{turn}"); sent[turn]=len(p)
    msgs.append({"role":"user","content":f"step {turn}"})
    msgs.append({"role":"assistant","content":[{"type":"tool_use","id":f"tu{turn}","name":"q","input":{}}]})
    msgs.append({"role":"user","content":[
        {"type":"tool_result","tool_use_id":f"tu{turn}","content":p},{"type":"text","text":"go"}]})
    fwd=send(list(msgs))
    print(f"\n--- request at turn {turn} ---")
    idx=0
    for m in fwd["messages"]:
        c=m.get("content")
        if isinstance(c,list):
            for b in c:
                if isinstance(b,dict) and b.get("type")=="tool_result":
                    body_s=b["content"] if isinstance(b["content"],str) else json.dumps(b["content"])
                    orig=sent[idx]
                    pct=(1-len(body_s)/orig)*100
                    newest = " <-- NEWEST (live zone)" if idx==turn else ""
                    state="compressed" if pct>10 else "VERBATIM"
                    print(f"   tool_result from turn {idx}: {orig:>6} -> {len(body_s):>6}  ({pct:5.1f}% saved)  {state}{newest}")
                    idx+=1
