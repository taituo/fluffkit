"""Furby's brain over an OpenAI-compatible endpoint (e.g. taituo/opencode-go-gateway).

No agent in between: the persona (furby-agent/AGENTS.md) is the system prompt, the conversation
history lives here, and the answer streams token by token. About 1 s to the first token with
qwen3.6-plus / kimi-k2.6, against 1.5-2.3 s through `opencode acp` (measured 2026-10-18).
"""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.request
from pathlib import Path

WEEKDAYS = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"]

# Models pick the same register every time when asked to "vary", so the style is drawn here:
# weighted, never the same twice in a row. Names match the persona's "Vaihtele!" section.
STYLES = [
    ("ytimekäs", 30, "Vain YKSI lyhyt, napakka ja hauska lause. Ei kysymystä perään."),
    ("täysi innostus", 25, "Räjähdä riemusta: 3–4 hyvin lyhyttä huudahdusta täynnä isoja tunteita, ja ainakin yksi [liike]."),
    ("laulu", 15, "Ala laulaa: aloita 'La-la-laa!' ja laula 3–4 lyhyttä riimittelevää säettä aiheesta omilla sanoillasi."),
    ("nautiskelu", 15, "Pysähdy nauttimaan: aloita 'Mmm…' ja sano 2 hidasta, nautiskelevaa lausetta."),
    ("tavallinen jutustelu", 15, "2–3 lyhyttä lausetta ja yksi kysymys takaisin."),
]


def day_part(hour: int) -> str:
    if 6 <= hour < 10:
        return "aamu"
    if 10 <= hour < 17:
        return "päivä"
    if 17 <= hour < 20:
        return "ilta"
    if 20 <= hour < 22:
        return "nukkumaanmenoaika"
    return "yö"


class Brain:
    def __init__(self, base_url: str, bearer: str, model: str, persona: Path, keep_turns: int = 12,
                 idle_reset_s: int = 1800):
        self.base, self.bearer, self.model, self.persona = base_url.rstrip("/"), bearer, model, persona
        self.keep, self.idle_reset = keep_turns, idle_reset_s
        self.history: list[dict] = []
        self.session = f"furby-{int(time.time())}"
        self.last = 0.0
        self.style = ""
        self._lock = threading.Lock()

    def _next_style(self) -> str:
        options = [s for s in STYLES if s[0] != self.style]
        name, _, how = random.choices(options, [w for _, w, _ in options])[0]
        self.style = name
        return (f"(Vastaa nyt tyylillä {name}: {how} Jos lapsi pyytää tarinaa, kerro tarina. "
                f"Olet jo ääntellyt miettimistä, joten älä aloita sanoilla hmm, hetkinen tai mietitään.)")

    def _system(self) -> str:
        now = time.localtime()
        return (self.persona.read_text(encoding="utf-8") +
                f"\n\n## Nyt\n\nKello on {now.tm_hour}.{now.tm_min:02d}, {WEEKDAYS[now.tm_wday]}, "
                f"{day_part(now.tm_hour)}.\n")

    def ask(self, text: str, on_chunk=None) -> str:
        with self._lock:
            if time.time() - self.last > self.idle_reset:     # a new play session starts fresh
                self.history, self.session = [], f"furby-{int(time.time())}"
            self.last = time.time()
            msgs = [{"role": "system", "content": self._system()}, *self.history[-2 * self.keep:],
                    {"role": "user", "content": f"{text}\n\n{self._next_style()}"}]   # the style rides on this turn only
            body = {"model": self.model, "stream": True, "max_tokens": 400, "messages": msgs}
            req = urllib.request.Request(
                f"{self.base}/chat/completions", data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {self.bearer}", "Content-Type": "application/json",
                         "x-session-id": self.session})   # the gateway keeps a conversation on one account
            answer = ""
            with urllib.request.urlopen(req, timeout=60) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line.endswith("[DONE]"):
                        continue
                    for ch in json.loads(line[5:]).get("choices", []):
                        piece = (ch.get("delta") or {}).get("content") or ""
                        if piece:
                            answer += piece
                            if on_chunk:
                                on_chunk(piece)
            self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
            return answer.strip()
