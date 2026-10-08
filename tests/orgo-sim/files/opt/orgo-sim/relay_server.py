#!/usr/bin/env python3
"""Fake openalan metered relay for the Orgo sim.

Endpoints (all under /api/relay):
  GET  /usage                              -> {jev_tasks_left_est, voice_minutes_left_est, resets_at}
  POST /openai/v1/audio/speech             -> audio bytes, or 402 credit_exhausted
  POST /openai/v1/audio/transcriptions     -> {"text": "sim transcript"}
  POST /jev/v1/systemone                   -> {"answers": {}}

Every request appends one JSON line to <requests-file>: method, path, auth
header, and body. What the relay answers is driven by a policy file read on
each request, so the test can flip credit state without restarting:

  <policy-file> {"voice_minutes_left": 10, "speech_status": 200}

The speech handler also performs the OpenRouter translation the hosted relay
implements upstream (change-openrouter.md): one chat.completions request to
openai/gpt-audio-mini with modalities [text, audio] and the strict verbatim
system prompt, against a fake upstream that just synthesises audio. The
upstream request body is appended to <upstream-file> so tests can check the
customer's text crossed the translation word for word — the fidelity the real
relay owes, checked without a live key.

usage: relay_server.py <host> <port> <requests-file> <upstream-file> <policy-file>
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

REQS, UPSTREAM, POLICY = sys.argv[3], sys.argv[4], sys.argv[5]

SPEECH_SYSTEM_PROMPT = ("Read the user's text aloud exactly, word for word. "
                        "Do not add, remove or change anything.")


def policy():
    try:
        with open(POLICY, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def record(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def translate_speech(body):
    """What the relay sends upstream for one /audio/speech call."""
    try:
        req = json.loads(body)
    except json.JSONDecodeError:
        req = {}
    upstream = {
        "model": "openai/gpt-audio-mini",
        "modalities": ["text", "audio"],
        "audio": {"voice": req.get("voice", "alloy"), "format": "mp3"},
        "messages": [
            {"role": "system", "content": SPEECH_SYSTEM_PROMPT},
            {"role": "user", "content": req.get("input", "")},
        ],
    }
    # The fake upstream: speaks the text verbatim and returns fake audio.
    record(UPSTREAM, upstream)
    return b"FAKEMP3BYTES"


class Handler(BaseHTTPRequestHandler):
    def _record(self, body):
        record(REQS, {"method": self.command, "path": self.path,
                      "auth": self.headers.get("Authorization"),
                      "body": body.decode("utf-8", "replace")})

    def _json(self, status, doc):
        payload = json.dumps(doc).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._record(b"")
        if self.path.endswith("/usage"):
            p = policy()
            self._json(200, {
                "jev_tasks_left_est": int(p.get("jev_tasks_left", 1000)),
                "voice_minutes_left_est": float(p.get("voice_minutes_left", 10)),
                "resets_at": p.get("resets_at", "2026-11-01T00:00:00Z"),
            })
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._record(body)
        if self.path.endswith("/audio/speech"):
            if int(policy().get("speech_status", 200)) == 402:
                self._json(402, {"error": "credit_exhausted", "kind": "voice"})
                return
            audio = translate_speech(body)
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
        elif self.path.endswith("/audio/transcriptions"):
            self._json(200, {"text": "sim transcript"})
        elif self.path.endswith("/v1/systemone"):
            self._json(200, {"answers": {}, "model": "typesafe/jev-1.13"})
        else:
            self._json(404, {"error": "not_found"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer((sys.argv[1], int(sys.argv[2])), Handler).serve_forever()
