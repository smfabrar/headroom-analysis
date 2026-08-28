"""Real-agent benchmark for the re-compression decay fix.

Protocol (per arm):
  Turn 1  agent calls list_files -> JSON array of every repo file.
          Headroom compresses it; some subset survives.
  Turn 2+ the user asks, one per turn, about files that DID survive turn 1.

If compression is idempotent, those survivors stay in context and the agent can
keep answering. If the compressed output is re-compressed each turn, survivors
are dropped one at a time and the agent starts answering wrongly about files it
could see moments earlier.

Ground truth is computed locally (the file exists), so grading is exact.
Model: gpt-4o-mini -- Headroom's own eval default.
"""
import json, os, subprocess, sys, time, urllib.request

BASE = os.environ["OPENAI_API_BASE"]; KEY = os.environ["OPENAI_API_KEY"]
MODEL = os.environ.get("AGENT_MODEL", "gpt-4o-mini")
REPO = os.environ["AGENT_REPO"]; CAP = os.environ["CAPTURE"]
TURNS = int(os.environ.get("BENCH_TURNS", "8"))
SALT = os.environ.get("BENCH_SALT", f"b{time.time_ns():019d}")

TOOLS = [{"type":"function","function":{"name":"list_files","description":
  "List every file in the repository.","parameters":{"type":"object","properties":{},"required":[]}}}]

def repo_files():
    out=[]
    for root,dirs,files in os.walk(REPO):
        dirs[:]=[d for d in dirs if d!=".git"]
        for f in files: out.append(os.path.relpath(os.path.join(root,f),REPO))
    return sorted(out)

def post(payload):
    req=urllib.request.Request(f"{BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {KEY}"})
    with urllib.request.urlopen(req,timeout=300) as r: return json.loads(r.read())

def forwarded_tool_payload(salt):
    """What the model actually received for the tool result, this request."""
    rec=None
    for line in open(CAP).read().strip().split("\n"):
        if line and salt in line: rec=json.loads(line)
    if not rec: return None
    d=json.loads(rec["body"])
    for m in d.get("messages",[]):
        if m.get("role")=="tool":
            return m.get("content")
    return None

def run():
    files=repo_files()
    sysmsg={"role":"system","content":f"Marker {SALT}. You are a repository assistant. "
            "Use list_files once, then answer follow-up questions from what you have."}
    msgs=[sysmsg,{"role":"user","content":"List every file in the repository."}]
    r=post({"model":MODEL,"messages":msgs,"tools":TOOLS,"max_tokens":300})
    m=r["choices"][0]["message"]; msgs.append(m)
    if not m.get("tool_calls"):
        print("  agent did not call the tool"); return []
    c=m["tool_calls"][0]
    msgs.append({"role":"tool","tool_call_id":c["id"],"content":json.dumps(files)})
    # what survived turn 1?
    r=post({"model":MODEL,"messages":msgs,"tools":TOOLS,"max_tokens":200})
    msgs.append(r["choices"][0]["message"])
    payload=forwarded_tool_payload(SALT) or ""
    survivors=[f for f in files if f in payload]
    print(f"  repo files={len(files)}  survived turn 1={len(survivors)}")
    if len(survivors) < 3:
        print("  too few survivors to probe"); return []
    probes=survivors[:TURNS]

    rows=[]
    for t,tgt in enumerate(probes,1):
        msgs.append({"role":"user","content":
            f"From the file list you already have: is {tgt} present? Answer strictly Yes or No."})
        r=post({"model":MODEL,"messages":msgs,"max_tokens":10})
        a=r["choices"][0]["message"]; msgs.append(a)
        said=(a.get("content") or "").strip().lower().startswith("yes")
        payload=forwarded_tool_payload(SALT) or ""
        in_ctx=tgt in payload
        n_ctx=len([f for f in files if f in payload])
        rows.append(dict(turn=t,target=tgt,said_yes=said,in_context=in_ctx,
                         items_in_context=n_ctx,correct=said))  # gt is always True
        print(f"  turn {t}: {tgt[:38]:<38} in_ctx={str(in_ctx):<5} said={'Yes' if said else 'No':<3} "
              f"items={n_ctx}")
    return rows

if __name__=="__main__":
    rows=run()
    if rows:
        acc=sum(r["correct"] for r in rows)/len(rows)
        ret=sum(r["in_context"] for r in rows)/len(rows)
        print(f"  ==> accuracy {sum(r['correct'] for r in rows)}/{len(rows)} = {acc:.0%}"
              f"   still-in-context {ret:.0%}"
              f"   items first->last {rows[0]['items_in_context']}->{rows[-1]['items_in_context']}")
    json.dump(rows,open(os.environ.get("BENCH_OUT","research/data/agent_decay.json"),"w"),indent=2)
