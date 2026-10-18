"""fluffkit panel: a local web page with a button per pack item, plus a live BLE debugger.

Keeps one BLE connection to Furby open (reconnects when Furby wakes up again) and streams
every GeneralPlus / Nordic notification to the page.

    .venv/bin/python panel.py out/hassut.json        # then open http://127.0.0.1:8765
    .venv/bin/python panel.py fi.json@12 dance.json@13   # several uploaded packs, switch with one click
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import wave
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pyfluff.furby import FurbyConnect
from pyfluff.protocol import FileTransferMode, FurbyMessage

HERE = Path(__file__).parent
DLC_SLOTS = 14
SR = 16000
SOUNDS = Path(os.environ.get("FLUFFKIT_SOUNDS", HERE / "sounds"))  # generated sound bank
MUSIC_STEP_S = 4  # how often Furby changes gesture during a song
PLAYER = ["afplay"] if platform.system() == "Darwin" else ["aplay", "-q"]
PITCH = float(os.environ.get("FLUFFKIT_SPEAK_PITCH", "3"))  # semitones, like `fluffkit pack --pitch 3`


def eleven_pcm(text: str, voice: str, key: str) -> bytes:
    """ElevenLabs TTS as 16 kHz mono s16le."""
    body = {"text": text, "model_id": os.environ.get("FLUFFKIT_ELEVEN_MODEL", "eleven_multilingual_v2")}
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_{SR}",
        data=json.dumps(body).encode(), headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def eleven_post(path: str, key: str, body: dict) -> bytes:
    """POST to the ElevenLabs API, return the audio bytes (mp3)."""
    req = urllib.request.Request(f"https://api.elevenlabs.io{path}", data=json.dumps(body).encode(),
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def pitch_up(pcm: bytes) -> bytes:
    """Raise pitch by PITCH semitones, same length (keeps the beak envelope in sync)."""
    if not PITCH or not shutil.which("ffmpeg"):
        return pcm
    f = 2 ** (PITCH / 12)
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
         "-af", f"asetrate={SR}*{f:.5f},aresample={SR},atempo={1 / f:.5f}", "-f", "s16le", "-"],
        input=pcm, capture_output=True)
    return r.stdout if r.returncode == 0 and r.stdout else pcm


def describe(src: str, d: bytes) -> str:
    """Human-readable meaning of a notification, as far as bluefluff/PyFluff know it."""
    if src != "gp" or not d:
        return ""
    k = d[0]
    if k == 0x20 and len(d) > 1:
        try:
            return FurbyMessage(d[1]).name
        except ValueError:
            return "FurbyMessage ?"
    if k == 0x21:
        return "sensor"
    if k == 0x24 and len(d) > 1:
        try:
            return "file transfer: " + FileTransferMode(d[1]).name
        except ValueError:
            return "file transfer ?"
    if k == 0x73 and len(d) >= 13:
        name = d[2:10].decode("ascii", "replace").strip("\x00")
        size = int.from_bytes(d[10:13], "big")
        return f"slot {d[1]}: " + (f"{name} {size} bytes" if any(d[2:13]) else "empty")
    if k == 0x74 and len(d) > 2:
        return f"slot {d[1]} deleted ({d[2]})"
    if k == 0xdc and len(d) > 2:
        return {1: f"slot {d[1]} loaded", 2: f"slot {d[1]} activated", 4: f"slot {d[1]} deactivated"}.get(
            d[2], f"ReportDLC slot {d[1]} code {d[2]}")
    if k == 0x72:
        return "slot allocation"
    if k == 0xfe and len(d) > 1:
        return f"GP firmware {d[1]}"
    return ""


class Hub:
    """One BLE connection + fan-out of events to every open page."""

    def __init__(self, address: str | None) -> None:
        self.address = address
        self.furby: FurbyConnect | None = None
        self.listeners: set[asyncio.Queue] = set()
        self.lock = asyncio.Lock()
        self.t0 = time.monotonic()
        self.state = "disconnected"

    def emit(self, kind: str, **data) -> None:
        ev = {"t": round(time.monotonic() - self.t0, 2), "kind": kind, **data}
        for q in list(self.listeners):
            if q.qsize() < 500:
                q.put_nowait(ev)

    def set_state(self, s: str) -> None:
        self.state = s
        self.emit("state", state=s)

    def _note(self, src: str, d: bytes) -> None:
        self.emit("rx", src=src, hex=d.hex(":"), note=describe(src, d))

    async def run(self) -> None:
        """Connect, stay connected, reconnect after Furby sleeps."""
        while True:
            if self.furby and self.furby.connected:
                await asyncio.sleep(1)
                continue
            self.set_state("searching")
            f = FurbyConnect()
            try:
                await f.connect(self.address)
            except Exception as e:  # Furby asleep / out of range
                self.emit("log", text=f"connect failed: {e}")
                self.set_state("disconnected")
                await asyncio.sleep(3)
                continue
            f.add_gp_callback(lambda d: self._note("gp", d))
            f.add_nordic_callback(lambda d: self._note("nordic", d))
            self.furby = f
            self.set_state("connected")
            asyncio.create_task(self._keepalive(f))

    async def _keepalive(self, f: FurbyConnect) -> None:
        """20 06 every 3 s, as furby-connect-ai does: keeps the link (and Furby) awake."""
        while f.connected:
            await asyncio.sleep(3)
            try:
                await f._write_gp(bytes([0x20, 0x06]))
            except Exception:
                return

    async def send_gp(self, data: bytes) -> None:
        f = self.furby
        if not f or not f.connected:
            raise HTTPException(503, "Furby not connected")
        async with self.lock:
            self.emit("tx", hex=data.hex(":"))
            await f._write_gp(data)


def make_app(hub: Hub, packs: list[dict]) -> FastAPI:
    current = {"pack": 0}

    def mapping() -> dict:
        return packs[current["pack"]]["items"]

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(hub.run())
        yield
        task.cancel()
        if hub.furby:
            await hub.furby.disconnect()

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def page():
        return FileResponse(HERE / "panel.html")

    @app.get("/api/items")
    async def items():
        return {"state": hub.state, "pack": current["pack"],
                "packs": [{"name": p["name"], "slot": p["slot"]} for p in packs],
                "items": [{"key": k, **v} for k, v in mapping().items()]}

    @app.post("/api/pack/{n}")
    async def switch_pack(n: int):
        """Show pack n; if it has a slot, load + activate it on Furby (no upload)."""
        if not 0 <= n < len(packs):
            raise HTTPException(404, "no such pack")
        p = packs[n]
        current["pack"] = n  # before the awaits, so the buttons never send the other pack's codes
        if p["slot"] is not None:
            hub.emit("log", text=f"activate pack {p['name']} in slot {p['slot']}")
            await hub.send_gp(bytes([0x60, p["slot"]]))
            await asyncio.sleep(2)
            await hub.send_gp(bytes([0x61]))
        return {"ok": True}

    @app.get("/api/events")
    async def events(request: Request):
        q: asyncio.Queue = asyncio.Queue()
        hub.listeners.add(q)
        q.put_nowait({"t": 0, "kind": "state", "state": hub.state})

        async def stream():
            try:
                while not await request.is_disconnected():
                    try:
                        ev = await asyncio.wait_for(q.get(), 15)
                        yield f"data: {json.dumps(ev)}\n\n"
                    except TimeoutError:
                        yield ": ping\n\n"
            finally:
                hub.listeners.discard(q)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/say/{key}")
    async def say(key: str):
        items = mapping()
        if key not in items:
            raise HTTPException(404, f"no item {key}")
        a = items[key]["action"]
        hub.emit("log", text=f"say {key}: {items[key]['text']}")
        await hub.send_gp(bytes([0x13, 0x00, *a]))
        return {"ok": True}

    # ---- sound bank: audio plays on this computer, Furby only performs silent gestures
    SOUNDS.mkdir(parents=True, exist_ok=True)
    bank_file = SOUNDS / "bank.json"
    bank: list[dict] = json.loads(bank_file.read_text(encoding="utf-8")) if bank_file.exists() else []

    async def gesture(action: list[int], why: str) -> None:
        if hub.furby and hub.furby.connected:
            hub.emit("log", text=f"gesture {'/'.join(map(str, action))}: {why}")
            try:
                await hub.send_gp(bytes([0x13, 0x00, *action]))
            except HTTPException:
                pass

    async def perform(snd: dict) -> None:
        """Play a bank sound and drive Furby with the active pack's silent items.
        speech: one beak ("talk N s") action as long as the speech; sfx: one body gesture;
        music: body gesture and beak in turns every few seconds until the song ends."""
        items = list(mapping().values())
        talk = sorted((v["talk"], v["action"]) for v in items if "talk" in v)
        moves = [v["action"] for v in items if v.get("gesture")]
        secs = snd["seconds"]

        def talk_for(s: float):
            return next((a for t, a in talk if t >= s), talk[-1][1] if talk else None)

        player = await asyncio.create_subprocess_exec(*PLAYER, str(SOUNDS / snd["file"]))
        if snd["kind"] == "speech" and talk:
            await gesture(talk_for(secs), f"beak for {secs:.1f} s of speech")
        elif snd["kind"] == "sfx" and (moves or talk):
            await gesture(random.choice(moves) if moves else talk_for(secs), "sound effect")
        elif snd["kind"] == "music":
            n = 0
            while player.returncode is None:
                if n % 2 == 0 and moves:
                    await gesture(random.choice(moves), "dance")
                elif talk:
                    await gesture(talk_for(MUSIC_STEP_S), "sing")
                n += 1
                try:
                    await asyncio.wait_for(player.wait(), MUSIC_STEP_S)
                except TimeoutError:
                    pass
        await player.wait()

    async def generate(kind: str, prompt: str, seconds: float) -> dict:
        key = os.environ.get("ELEVENLABS_API_KEY") or ""
        if not key:
            raise HTTPException(500, "ELEVENLABS_API_KEY is not set")
        t0 = time.monotonic()
        stem = f"{len(bank) + 1:03d}_{kind}"
        try:
            if kind == "speech":
                voice = os.environ.get("FLUFFKIT_ELEVEN_VOICE", "cgSgspJ2msm6clMCkdW9")
                pcm = pitch_up(await asyncio.to_thread(eleven_pcm, prompt, voice, key))
                path = SOUNDS / f"{stem}.wav"
                write_wav(path, pcm, SR)
            elif kind == "sfx":
                path = SOUNDS / f"{stem}.mp3"
                path.write_bytes(await asyncio.to_thread(
                    eleven_post, "/v1/sound-generation", key,
                    {"text": prompt, "duration_seconds": max(0.5, min(30.0, seconds)), "prompt_influence": 0.7}))
            elif kind == "music":
                path = SOUNDS / f"{stem}.mp3"
                path.write_bytes(await asyncio.to_thread(
                    eleven_post, "/v1/music", key,
                    {"prompt": prompt, "music_length_ms": int(max(5.0, min(120.0, seconds)) * 1000)}))
            else:
                raise HTTPException(400, f"unknown kind {kind}")
        except urllib.error.HTTPError as e:
            raise HTTPException(502, f"ElevenLabs {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")
        snd = {"kind": kind, "prompt": prompt, "file": path.name, "seconds": round(duration(path), 2)}
        bank.append(snd)
        bank_file.write_text(json.dumps(bank, ensure_ascii=False, indent=1), encoding="utf-8")
        hub.emit("log", text=f"{kind} ready in {time.monotonic() - t0:.1f} s ({snd['seconds']} s): {prompt}")
        return snd

    @app.post("/api/speak")
    async def speak(body: dict):
        """Instant speech: ElevenLabs -> this computer's speaker, Furby moves its beak (silent talk item)."""
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(400, "empty text")
        await perform(await generate("speech", text, 0))
        return {"ok": True}

    @app.post("/api/sound")
    async def new_sound(body: dict):
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            raise HTTPException(400, "empty prompt")
        snd = await generate(str(body.get("kind", "sfx")), prompt, float(body.get("seconds", 3)))
        await perform(snd)
        return {"ok": True}

    @app.get("/api/sounds")
    async def sounds():
        return [{"id": i, **s} for i, s in enumerate(bank)]

    @app.post("/api/sounds/{i}/play")
    async def play_sound(i: int):
        if not 0 <= i < len(bank):
            raise HTTPException(404, "no such sound")
        await perform(bank[i])
        return {"ok": True}

    @app.post("/api/action")
    async def action(body: dict):
        a = [int(body[k]) for k in ("input", "index", "subindex", "specific")]
        await hub.send_gp(bytes([0x13, 0x00, *a]))
        return {"ok": True}

    @app.post("/api/antenna")
    async def antenna(body: dict):
        await hub.send_gp(bytes([0x14, int(body["r"]), int(body["g"]), int(body["b"])]))
        return {"ok": True}

    @app.post("/api/debugmenu")
    async def debugmenu():
        await hub.send_gp(bytes([0xdb]))
        return {"ok": True}

    @app.post("/api/slots")
    async def slots():
        for s in range(DLC_SLOTS):
            await hub.send_gp(bytes([0x73, s]))
            await asyncio.sleep(0.3)
        return {"ok": True}

    @app.post("/api/activate/{slot}")
    async def activate(slot: int):
        await hub.send_gp(bytes([0x60, slot]))
        await asyncio.sleep(2)
        await hub.send_gp(bytes([0x61]))
        return {"ok": True}

    @app.post("/api/deactivate/{slot}")
    async def deactivate(slot: int):
        await hub.send_gp(bytes([0x62, slot]))
        return {"ok": True}

    @app.post("/api/raw")
    async def raw(body: dict):
        try:
            data = bytes.fromhex(body["hex"].replace(":", "").replace(" ", ""))
        except ValueError:
            raise HTTPException(400, "not hex")
        if not data:
            raise HTTPException(400, "empty")
        await hub.send_gp(data)
        return {"ok": True}

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("maps", nargs="*", default=["pack.json"],
                    help="pack maps written by `fluffkit pack`; add @SLOT (e.g. hassut.json@12) to switch "
                         "Furby to that already-uploaded slot when the pack is chosen")
    ap.add_argument("--address", help="Furby MAC / CoreBluetooth UUID (default: scan)")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    packs = []
    for m in a.maps:
        path, _, slot = m.partition("@")
        packs.append({"name": Path(path).stem, "slot": int(slot) if slot else None,
                      "items": json.loads(Path(path).read_text(encoding="utf-8"))})
    uvicorn.run(make_app(Hub(a.address), packs), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
