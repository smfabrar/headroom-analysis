"""A minimal but genuine function-calling coding agent.

Used because aider does NOT use tool calling -- it passes file contents as
prose (measured: 0 tool messages, 0 JSON arrays in captured traffic). The
scalar-array compression path can only be exercised by an agent whose tool
results are JSON arrays, which is how Claude Code / Codex / Cursor operate.

Tools mirror what such agents actually expose: list_files, grep, read_file,
run_tests. Their results are returned as JSON -- list_files and grep yield
arrays of strings, i.e. scalar arrays.
"""
import json, os, re, subprocess, sys, urllib.request

BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
KEY = os.environ["OPENAI_API_KEY"]
MODEL = os.environ.get("AGENT_MODEL", "gpt-4o-mini")
REPO = os.environ["AGENT_REPO"]
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "8"))

TOOLS = [
 {"type":"function","function":{"name":"list_files","description":
   "List repository files matching an optional glob-ish substring.",
   "parameters":{"type":"object","properties":{
     "contains":{"type":"string","description":"substring filter, empty for all"}},
     "required":[]}}},
 {"type":"function","function":{"name":"grep","description":
   "Search the repository for a regex; returns matching 'path:line:text' entries.",
   "parameters":{"type":"object","properties":{
     "pattern":{"type":"string"}},"required":["pattern"]}}},
 {"type":"function","function":{"name":"read_file","description":"Read a file.",
   "parameters":{"type":"object","properties":{"path":{"type":"string"}},
     "required":["path"]}}},
 {"type":"function","function":{"name":"run_tests","description":
   "Run the test suite; returns the list of test result lines.",
   "parameters":{"type":"object","properties":{},"required":[]}}},
]

def _walk():
    out=[]
    for root,dirs,files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            out.append(os.path.relpath(os.path.join(root,f), REPO))
    return sorted(out)

def call_tool(name, args):
    if name == "list_files":
        sub = (args or {}).get("contains","")
        return [p for p in _walk() if sub in p]           # scalar array
    if name == "grep":
        pat = re.compile(args["pattern"])
        hits=[]
        for p in _walk():
            if not p.endswith(".py"): continue
            try: txt=open(os.path.join(REPO,p)).read().splitlines()
            except Exception: continue
            for i,l in enumerate(txt,1):
                if pat.search(l): hits.append(f"{p}:{i}:{l.strip()}")
        return hits                                        # scalar array
    if name == "read_file":
        try: return open(os.path.join(REPO,args["path"])).read()
        except Exception as e: return f"ERROR: {e}"
    if name == "run_tests":
        r = subprocess.run([sys.executable,"-m","pytest","-q","--no-header"],
                           cwd=REPO, capture_output=True, text=True, timeout=120)
        return (r.stdout+r.stderr).splitlines()            # scalar array
    return f"unknown tool {name}"

def post(payload):
    req=urllib.request.Request(f"{BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())

def run(task):
    msgs=[{"role":"system","content":
           "You are a coding assistant working in a repository. "
           "Use the tools to investigate before answering. Be concise."},
          {"role":"user","content":task}]
    for step in range(MAX_STEPS):
        resp=post({"model":MODEL,"messages":msgs,"tools":TOOLS,"max_tokens":600})
        m=resp["choices"][0]["message"]
        msgs.append(m)
        calls=m.get("tool_calls")
        if not calls:
            print(f"  [{step}] final: {(m.get('content') or '')[:160]}")
            return msgs
        for c in calls:
            fn=c["function"]["name"]
            try: args=json.loads(c["function"]["arguments"] or "{}")
            except Exception: args={}
            out=call_tool(fn,args)
            n = len(out) if isinstance(out,list) else 1
            print(f"  [{step}] {fn}({args}) -> {'array n='+str(n) if isinstance(out,list) else 'text'}")
            msgs.append({"role":"tool","tool_call_id":c["id"],
                         "content": json.dumps(out) if not isinstance(out,str) else out})
    return msgs

if __name__ == "__main__":
    for t in json.loads(os.environ.get("AGENT_TASKS", "[]")) or [sys.argv[1]]:
        print(f"\n=== TASK: {t}")
        run(t)
