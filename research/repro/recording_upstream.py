"""Recording forward-proxy: captures the exact body Headroom forwards, then
relays it to the REAL provider and streams the response back.

Unlike fake_upstream.py this returns genuine model output, so an agent loop
actually progresses. Used for Phase A traffic capture.
"""
import json, os, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = os.environ.get("CAPTURE", "/tmp/captured.jsonl")
TARGET = os.environ.get("REAL_UPSTREAM", "https://api.openai.com")
PORT = int(os.environ.get("REC_PORT", "8798"))

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            with open(OUT, "a") as f:
                f.write(json.dumps({"path": self.path,
                                    "body": raw.decode("utf-8", "replace")}) + "\n")
        except Exception:
            pass
        hdrs = {k: v for k, v in self.headers.items()
                if k.lower() not in ("host", "content-length", "connection",
                                     "accept-encoding")}
        req = urllib.request.Request(TARGET + self.path, data=raw, headers=hdrs,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() in ("content-type",):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length","0"); self.end_headers()
    def log_message(self, *a): pass

print(f"recording upstream on {PORT} -> {TARGET}, capture={OUT}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
