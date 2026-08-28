"""Fake Anthropic upstream whose reply can be scripted via a control file.

Writing a hash into /tmp/next_retrieve makes the next reply a tool_use calling
headroom_retrieve(hash=...) -- i.e. it simulates a model that decides to retrieve.
"""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
OUT=os.environ.get("CAPTURE","/tmp/cap.jsonl")
CTL=os.environ.get("CTL","/tmp/next_retrieve")

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n=int(self.headers.get("Content-Length",0)); raw=self.rfile.read(n)
        with open(OUT,"a") as f: f.write(json.dumps({"path":self.path,"body":raw.decode("utf-8","replace")})+"\n")
        hsh=None
        if os.path.exists(CTL):
            hsh=open(CTL).read().strip() or None
            os.remove(CTL)
        if hsh:
            content=[{"type":"tool_use","id":"ccr_call_1","name":"headroom_retrieve","input":{"hash":hsh}}]
            stop="tool_use"
        else:
            content=[{"type":"text","text":"ok"}]; stop="end_turn"
        resp=json.dumps({"id":"msg_fake","type":"message","role":"assistant",
            "model":"claude-sonnet-4-5-20250929","content":content,"stop_reason":stop,
            "usage":{"input_tokens":10,"output_tokens":2}}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(resp))); self.end_headers(); self.wfile.write(resp)
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self): self.send_response(200); self.end_headers()
    def log_message(self,*a): pass
HTTPServer(("127.0.0.1",8799),H).serve_forever()
