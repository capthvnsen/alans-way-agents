#!/usr/bin/env python3
"""Tiny callback sink for the Orgo sim: bootstrap POSTs the Tailscale login
URL here and every body lands in <outfile> as JSON for the test to read.

usage: callback_server.py <bind-host> <port> <outfile>
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def main() -> int:
    host, port, outfile = sys.argv[1], int(sys.argv[2]), sys.argv[3]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            with open(outfile, "wb") as f:
                f.write(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())

        def log_message(self, *args):
            pass

    HTTPServer((host, port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
