"""Fake Anthropic API: records the exact body Headroom forwards upstream."""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = os.environ.get("CAPTURE", "/tmp/captured.jsonl")

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        with open(OUT, "a") as f:
            f.write(json.dumps({"path": self.path, "body": raw.decode("utf-8", "replace")}) + "\n")
        resp = json.dumps({
            "id": "msg_fake", "type": "message", "role": "assistant",
            "model": "claude-sonnet-4-5-20250929",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

PORT = int(os.environ.get("UPSTREAM_PORT", "8799"))
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
