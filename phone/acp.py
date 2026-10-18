"""Minimal ACP (Agent Client Protocol) client: talk to `opencode acp` over stdio JSON-RPC.

One long-lived agent process and one session, so the conversation keeps its context.
The client grants no file system or terminal access and cancels every permission request,
so the agent can only answer in text.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path


class ACPAgent:
    def __init__(self, cmd: list[str], cwd: Path):
        self.cmd, self.cwd = cmd, cwd
        self.proc: subprocess.Popen | None = None
        self.session: str | None = None
        self._id = 0
        self._pending: dict[int, dict] = {}
        self._cv = threading.Condition()
        self._chunks: list[str] = []
        self._on_chunk = None          # callback for the prompt in flight
        self._lock = threading.Lock()  # one prompt at a time

    # ---- JSON-RPC plumbing
    def _start(self) -> None:
        self.proc = subprocess.Popen(self.cmd, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._reader, daemon=True).start()
        self._call("initialize", {"protocolVersion": 1,
                                  "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                                         "terminal": False}})
        self.session = self._call("session/new", {"cwd": str(self.cwd), "mcpServers": []})["sessionId"]

    def _send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _call(self, method: str, params: dict, timeout: float = 180) -> dict:
        with self._cv:
            self._id += 1
            rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        with self._cv:
            if not self._cv.wait_for(lambda: rid in self._pending, timeout):
                raise TimeoutError(f"{method}: no answer in {timeout} s")
            msg = self._pending.pop(rid)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result") or {}

    def _reader(self) -> None:
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "method" in msg and "id" in msg:      # request from the agent
                self._answer(msg)
            elif "method" in msg:                    # notification
                u = msg.get("params", {}).get("update", {})
                if u.get("sessionUpdate") == "agent_message_chunk" and u.get("content", {}).get("type") == "text":
                    self._chunks.append(u["content"]["text"])
                    if self._on_chunk:
                        self._on_chunk(u["content"]["text"])
            elif "id" in msg:                        # response to one of ours
                with self._cv:
                    self._pending[msg["id"]] = msg
                    self._cv.notify_all()

    def _answer(self, req: dict) -> None:
        if req["method"] == "session/request_permission":
            result = {"outcome": {"outcome": "cancelled"}}
            self._send({"jsonrpc": "2.0", "id": req["id"], "result": result})
        else:
            self._send({"jsonrpc": "2.0", "id": req["id"],
                        "error": {"code": -32601, "message": "not available to this agent"}})

    # ---- public
    def ask(self, text: str, on_chunk=None) -> str:
        """Send one user turn; on_chunk(text) is called for every piece of the answer as it arrives."""
        with self._lock:
            if not self.proc or self.proc.poll() is not None:
                self._start()
            self._chunks.clear()
            self._on_chunk = on_chunk
            try:
                self._call("session/prompt", {"sessionId": self.session, "prompt": [{"type": "text", "text": text}]})
            finally:
                self._on_chunk = None
            return "".join(self._chunks).strip()
