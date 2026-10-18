"""Serve the phone page to a USB-connected Android phone.

    ELEVENLABS_API_KEY=… python phone/serve.py        # then: adb reverse tcp:8766 tcp:8766
                                                     # and open http://localhost:8766 in the phone's Chrome

Chrome only allows Web Bluetooth on https or localhost; `adb reverse` makes the phone's localhost
reach this computer. Listens on 127.0.0.1 only, so /config.json (the ElevenLabs key) is reachable
just from this computer and the phone on the USB cable.
"""
import http.server
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
PORT = int(os.environ.get("PORT", "8766"))
sys.path.insert(0, str(HERE))
from acp import ACPAgent  # noqa: E402
from brain import Brain  # noqa: E402

# Furby's brain. Default: an OpenAI-compatible gateway (FURBY_LLM_URL, bearer from FURBY_LLM_BEARER or
# ~/.config/fluffkit/gateway_bearer), persona from phone/furby-agent/AGENTS.md.
# FURBY_BRAIN=acp uses `opencode acp` instead (slower: agent prompt + tools in between).
_bearer_file = Path.home() / ".config" / "fluffkit" / "gateway_bearer"
if os.environ.get("FURBY_BRAIN", "gateway") == "acp":
    AGENT = ACPAgent(os.environ.get("FURBY_AGENT_CMD", "opencode acp").split(), HERE / "furby-agent")
else:
    AGENT = Brain(os.environ.get("FURBY_LLM_URL", "http://127.0.0.1:8788/v1"),
                  os.environ.get("FURBY_LLM_BEARER") or (_bearer_file.read_text().strip() if _bearer_file.exists() else ""),
                  os.environ.get("FURBY_MODEL", "qwen3.6-plus"),
                  HERE / "furby-agent" / "AGENTS.md")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def do_GET(self):
        if self.path == "/config.json":
            # phone/furby-config.json (voice, filter, fillers, colours…) + the key, read fresh on every load
            cfg_file = HERE / "furby-config.json"
            cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
            body = json.dumps({**cfg, "elevenlabs_key": os.environ.get("ELEVENLABS_API_KEY", "")}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/chat-stream":
            return self._chat_stream()
        if self.path != "/chat":
            self.send_error(404)
            return
        try:
            text = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("text", "")
            reply = AGENT.ask(str(text)[:2000]) if text.strip() else ""
            body, code = json.dumps({"reply": reply}).encode(), 200
        except Exception as e:  # agent down, timeout, protocol error
            body, code = json.dumps({"error": str(e)}).encode(), 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _chat_stream(self):
        """Answer as newline-delimited JSON while the agent is still writing: {"t": piece} ... {"done": true}.
        HTTP/1.0 without Content-Length, so the body simply ends when the answer does."""
        text = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("text", "")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def out(obj):
            try:
                self.wfile.write((json.dumps(obj) + "\n").encode())
                self.wfile.flush()
            except OSError:
                pass  # the phone went away; let the agent finish anyway
        try:
            if str(text).strip():
                AGENT.ask(str(text)[:2000], on_chunk=lambda piece: out({"t": piece}))
            out({"done": True})
        except Exception as e:
            out({"error": str(e)})

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    print(f"http://127.0.0.1:{PORT}  (adb reverse tcp:{PORT} tcp:{PORT})")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
