import json, urllib.request, os, random, string
CAP=os.environ["CAP"]; PORT=os.environ.get("PORT","8810")
random.seed(33)
W=[''.join(random.choices(string.ascii_lowercase,k=8)) for _ in range(4000)]
def payload(tag): return json.dumps([{"c":tag,"id":j,"body":" ".join(random.choices(W,k=60))} for j in range(60)])
def send(msgs):
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,"messages":msgs}
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
    urllib.request.urlopen(req,timeout=90).read()
    return json.loads(json.loads(open(CAP).read().strip().split("\n")[-1])["body"])
def newest_ratio(fwd, orig_len):
    last=None
    for m in fwd["messages"]:
        if isinstance(m.get("content"),list):
            for b in m["content"]:
                if b.get("type")=="tool_result": last=b["content"]
    s=last if isinstance(last,str) else json.dumps(last)
    return (1-len(s)/orig_len)*100

def convo(name, n_turns, prefix_tag):
    msgs=[]
    for t in range(n_turns):
        p=payload(f"{prefix_tag}{t}")
        msgs += [{"role":"user","content":f"{prefix_tag} step {t}"},
                 {"role":"assistant","content":[{"type":"tool_use","id":f"tu{t}","name":"q","input":{}}]},
                 {"role":"user","content":[{"type":"tool_result","tool_use_id":f"tu{t}","content":p},
                                           {"type":"text","text":"go"}]}]
        pct=newest_ratio(send(list(msgs)), len(p))
        print(f"  {name} turn {t}: newest tool_result {pct:5.1f}% saved  {'OK' if pct>10 else '*** NOT COMPRESSED ***'}")

print("Conversation A (incremental, same proxy):"); convo("A",3,"A")
print("\nConversation B — BRAND NEW conversation, same proxy:"); convo("B",2,"B")
print("\nConversation A again, one MORE turn (continuing A):"); convo("A2",1,"A")
