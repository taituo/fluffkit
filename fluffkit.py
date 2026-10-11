#!/usr/bin/env python3
"""
fluffkit: custom audio for Furby Connect (2016) - any language, any sound.

Pipeline: text -> TTS (OpenAI / Piper / espeak-ng)  or  your own wav/mp3/flac/...
          -> 16 kHz mono -> A18 (fixed open A1800 encoder) -> DLC pack
          -> BLE upload (PyFluff) -> trigger with action 75/0/y/z

Commands:
  tts     "text" -o out.wav             text to speech
  encode  in.wav -o out.a18             any audio file -> Furby A18
  decode  in.a18 -o out.wav             A18 -> WAV (to listen)
  pack    pack.txt -o pack.dlc          build a pack (one item per line: text or audio file)
  check   pack.dlc [--export dir]       verify a pack, decode its tracks to WAV
  upload  pack.dlc                      upload (delete -> upload -> load -> activate)
  say     3 | 3 7 "night" | -          play item(s); "-" keeps the connection open and reads stdin
  slots                                 list the 60 slots (75/x/y/z)

Needs: python 3.11+, ffmpeg, a1800_codec (Releases, or: cd a1800 && cargo build --release);
upload/say: PyFluff (git clone https://github.com/martinwoodward/PyFluff && pip install -e PyFluff).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dlcpack import DLC, SLOTS  # noqa: E402

CACHE = Path(os.environ.get("FLUFFKIT_CACHE", Path.home() / ".cache" / "fluffkit"))
BASE_DLC_URL = "https://raw.githubusercontent.com/ctxis/Furby/master/dlc/dlc2/tu003410.dlc"
BASE_DLC_SHA256 = "efe11a82a7f837ebd8ab7a76e5873e0be4a0aa23ccedc73cb9c4601139c8e203"

SR = 16000
BITRATE = 16000            # every stock Furby track is 16 kbps
FRAME_SAMPLES = 320        # 20 ms
FRAME_BYTES = BITRATE // 800 * 2   # 40 bytes per frame
# 48-byte header written by A1800.DLL (copied from DLL-made files)
GP_HEADER = bytes.fromhex(
    "00ff00ff47454e4552414c504c55532053500000fe020e001000803e"
    "0000803e00000000000000000001000000000000")
MINIFIED_TRACK_BYTES = 128  # as in the Context IS demo that worked on a real Furby


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def codec_bin() -> str:
    for c in (os.environ.get("A1800_CODEC"), HERE / "bin" / "a1800_codec",
              HERE / "a1800" / "target" / "release" / "a1800_codec",
              shutil.which("a1800_codec")):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    die("a1800_codec not found: run `cargo build --release` in a1800/ or put a release binary in bin/")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"{cmd[0]} failed:\n{r.stderr[-2000:]}")


# ---------------------------------------------------------------- TTS

def tts(text: str, out_wav: Path, engine: str, voice: str | None, instructions: str | None) -> None:
    if engine == "openai":
        key = os.environ.get("OPENAI_API_KEY") or die("OPENAI_API_KEY is not set")
        body = {
            "model": os.environ.get("FLUFFKIT_TTS_MODEL", "gpt-4o-mini-tts"),
            "voice": voice or os.environ.get("FLUFFKIT_TTS_VOICE", "coral"),
            "input": text,
            "response_format": "wav",
        }
        ins = instructions or os.environ.get(
            "FLUFFKIT_TTS_INSTRUCTIONS",
            "Speak in the language of the text. You are a small, cheerful, slightly silly "
            "furry creature. Speak clearly, eagerly and a little fast.")
        if ins:
            body["instructions"] = ins
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out_wav.write_bytes(r.read())
    elif engine == "piper":
        model = voice or os.environ.get("FLUFFKIT_PIPER_MODEL") or die(
            "give --voice path/to/voice.onnx or set FLUFFKIT_PIPER_MODEL")
        p = subprocess.run(["piper", "--model", model, "--output_file", str(out_wav)],
                           input=text, text=True, capture_output=True)
        if p.returncode:
            die(p.stderr[-1500:])
    elif engine == "espeak":
        run(["espeak-ng", "-v", voice or os.environ.get("FLUFFKIT_ESPEAK_VOICE", "en"), "-s", "150", "-w", str(out_wav), text])
    else:
        die(f"unknown TTS engine: {engine}")


# ---------------------------------------------------------------- A18

def to_pcm16k(src: Path, dst: Path, pitch: float, gain_db: float, music: bool = False) -> None:
    """Any audio -> 16 kHz mono s16, shaped for Furby's tiny speaker.
    Speech: high-pass + dynamic normalisation. music=True: gentler, keeps dynamics."""
    af = ["highpass=f=80" if music else "highpass=f=120", "lowpass=f=7000"]
    if pitch:
        f = 2 ** (pitch / 12)
        af += [f"asetrate={SR}*{f:.5f}", f"aresample={SR}", f"atempo={1 / f:.5f}"]
    af += ["loudnorm=I=-16:TP=-1.0:LRA=11"] if music else \
          ["dynaudnorm=f=150:g=15", "loudnorm=I=-14:TP=-1.0:LRA=7"]
    if gain_db:
        af.append(f"volume={gain_db}dB")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", ",".join(af),
         "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])


def encode_a18_body(wav16: Path) -> bytes:
    """Return a track in Furby/DLL layout: u32 (frame bytes + 2) | u16 16000 | frames."""
    raw = wav16.read_bytes()
    # find the data chunk
    i = 12
    while i < len(raw) - 8:
        cid, sz = raw[i:i + 4], struct.unpack("<I", raw[i + 4:i + 8])[0]
        if cid == b"data":
            pcm = raw[i + 8:i + 8 + sz]
            break
        i += 8 + sz + (sz & 1)
    else:
        die("WAV has no data chunk")
    n = len(pcm) // 2
    # +1 frame of silence: the open encoder runs one frame behind the DLL, so the
    # first frame is dropped below and the timing then matches DLL output.
    pad = (-n) % FRAME_SAMPLES + FRAME_SAMPLES
    pcm += b"\x00\x00" * pad
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "in.wav"
        a = Path(td) / "out.a18"
        hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1,
                          SR, SR * 2, 2, 16, b"data", len(pcm))
        w.write_bytes(hdr + pcm)
        run([codec_bin(), "encode", str(w), str(a), "--bitrate", str(BITRATE)])
        jk = a.read_bytes()
    frames = jk[6:]
    frames = frames[FRAME_BYTES:]  # drop first frame (see above)
    assert len(frames) % FRAME_BYTES == 0
    return struct.pack("<IH", len(frames) + 2, BITRATE) + frames


def read_a18_body(path: Path) -> bytes:
    d = path.read_bytes()
    if d[:18] == GP_HEADER[:18]:
        d = d[0x30:]
    ln = struct.unpack("<I", d[:4])[0]
    return d[:4 + ln]


def decode_body(body: bytes, out_wav: Path) -> None:
    ln, br = struct.unpack("<IH", body[:6])
    # the open decoder expects the plain frame byte count
    fixed = struct.pack("<IH", ln - 2, br) + body[6:6 + ln - 2]
    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "x.a18"
        a.write_bytes(fixed)
        run([codec_bin(), "decode", str(a), str(out_wav)])


# ---------------------------------------------------------------- DLC

def base_dlc(path: str | None) -> Path:
    if path:
        return Path(path)
    p = CACHE / "tu003410.dlc"
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"downloading base DLC {BASE_DLC_URL}")
        with urllib.request.urlopen(BASE_DLC_URL, timeout=60) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != BASE_DLC_SHA256:
            die("base DLC checksum mismatch")
        p.write_bytes(data)
    return p


def read_phrases(path: Path) -> list[str]:
    lines = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            lines.append(ln)
    return lines


def phrase_to_body(item: str, args) -> tuple[bytes, str]:
    """A line is an audio file path (.wav/.mp3/.flac/.ogg/.m4a/.a18) or text for TTS. Cached by hash."""
    music = args.music
    for tag in ("[music]", "[sfx]"):
        if item.lower().startswith(tag):
            item, music = item[len(tag):].strip(), True
    p = Path(item).expanduser()
    if p.suffix.lower() == ".a18" and p.exists():
        return read_a18_body(p), p.name
    key = hashlib.sha256(json.dumps([item, args.engine, args.voice, args.instructions,
                                     args.pitch, args.gain, music]).encode()).hexdigest()[:16]
    cached = CACHE / "a18" / f"{key}.a18"
    if cached.exists():
        return cached.read_bytes(), item
    cached.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = p if p.exists() and p.suffix.lower() in (".wav", ".mp3", ".ogg", ".flac", ".m4a") else None
        if src is None:
            src = Path(td) / "tts.wav"
            tts(item, src, args.engine, args.voice, args.instructions)
        w16 = Path(td) / "16k.wav"
        to_pcm16k(src, w16, 0 if music else args.pitch, args.gain, music)
        body = encode_a18_body(w16)
    cached.write_bytes(body)
    return body, item


def cmd_pack(args) -> None:
    phrases = read_phrases(Path(args.phrases))
    if len(phrases) > len(SLOTS):
        die(f"too many items ({len(phrases)}), a pack has {len(SLOTS)} slots")
    D = DLC.load(base_dlc(args.base))
    if not args.keep_original_audio:
        D.minify_audio(MINIFIED_TRACK_BYTES)
    mapping = {}
    for i, item in enumerate(phrases):
        code, apl, track = SLOTS[i]
        body, label = phrase_to_body(item, args)
        D.set_phrase(apl, track, body)
        secs = (len(body) - 6) / FRAME_BYTES * 0.02
        mapping[str(i + 1)] = {"text": label, "action": list(code), "apl": apl, "amf": track,
                               "seconds": round(secs, 2)}
        print(f"{i + 1:2d}  {'/'.join(map(str, code)):10s} {secs:5.2f}s  {label}")
    out = Path(args.output)
    out.write_bytes(D.build())
    map_path = out.with_suffix(".json")
    map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    kb = out.stat().st_size / 1024
    print(f"\n{out}  {kb:.0f} kB  (BLE ~4 kB/s -> about {kb / 4 / 60:.1f} min upload)\nmap: {map_path}")
    verify(out, mapping, None)


def verify(path: Path, mapping: dict, export: Path | None) -> None:
    D = DLC.load(path)
    ok = 0
    for k, m in mapping.items():
        tr = D.audio_for(m["apl"])
        body = D.tracks[tr[0]] if tr else b""
        ln, br = struct.unpack("<IH", body[:6]) if len(body) >= 6 else (0, 0)
        good = tr == [m["amf"]] and br == BITRATE and (ln - 2) % FRAME_BYTES == 0 and len(body) == ln + 4
        ok += good
        if export and good:
            export.mkdir(parents=True, exist_ok=True)
            decode_body(body, export / f"{int(k):02d}.wav")
        if not good:
            print(f"  ERROR item {k}: {tr} {ln} {br}")
    print(f"check: {ok}/{len(mapping)} items point to the right track; DLC parses ({len(D.tracks)} tracks)")


def cmd_check(args) -> None:
    p = Path(args.dlc)
    mapping = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
    verify(p, mapping, Path(args.export) if args.export else None)


def cmd_slots(args) -> None:
    for i, (code, apl, track) in enumerate(SLOTS, 1):
        print(f"{i:2d}  {'/'.join(map(str, code))}")


# ---------------------------------------------------------------- BLE (PyFluff)

def _pyfluff():
    if os.environ.get("PYFLUFF_PATH"):
        sys.path.insert(0, os.environ["PYFLUFF_PATH"])
    try:
        from pyfluff.furby import FurbyConnect
        from pyfluff.dlc import DLCManager
    except ImportError:
        die("PyFluff not found: git clone https://github.com/martinwoodward/PyFluff && pip install -e PyFluff "
            "(or set PYFLUFF_PATH=/path/to/PyFluff)")
    return FurbyConnect, DLCManager


async def _connected(address: str | None):
    FurbyConnect, _ = _pyfluff()
    f = FurbyConnect()
    await f.connect(address)
    return f


def cmd_upload(args) -> None:
    import asyncio
    _, DLCManager = _pyfluff()

    async def go():
        f = await _connected(args.address)
        try:
            m = DLCManager(f)
            await f.set_antenna_color(255, 0, 0)
            print(f"deleting slot {args.slot}")
            await m.delete_dlc(args.slot)
            await asyncio.sleep(2)
            print("uploading... (Furby debug screen: 1 = receiving, 2 = done, 3 = active)")
            # announce the stock file name: the proven route (Context IS, furpy3) kept it
            with tempfile.TemporaryDirectory() as td:
                up = Path(td) / args.name
                shutil.copyfile(args.dlc, up)
                await m.upload_dlc(up, slot=args.slot, timeout=args.timeout)
            await m.load_dlc(args.slot)
            await asyncio.sleep(1)
            await m.activate_dlc()
            await f.set_antenna_color(0, 255, 0)
            print("done. If nothing plays: restart Furby and run `say 1`.")
        finally:
            await f.disconnect()
    asyncio.run(go())


def _resolve(mapping: dict, key: str) -> str:
    key = key.strip()
    if key in mapping:
        return key
    hits = [k for k, m in mapping.items() if key.lower() in m["text"].lower()]
    if not hits:
        raise KeyError(key)
    return hits[0]


def cmd_say(args) -> None:
    """say 3 | say 3 7 "good night" (chained, one connection) | say - (keep connection, read items from stdin)."""
    import asyncio
    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
    interactive = args.what == ["-"]
    if not interactive:
        try:
            keys = [_resolve(mapping, w) for w in args.what]
        except KeyError as e:
            die(f"no such item: {e.args[0]}")

    async def play(f, key):
        m = mapping[key]
        print(f"{key}: {'/'.join(map(str, m['action']))}  {m['text']}", flush=True)
        await f.trigger_action(*m["action"])
        await asyncio.sleep(m["seconds"] + args.gap)

    async def go():
        f = await _connected(args.address)
        try:
            if not interactive:
                for k in keys:
                    await play(f, k)
                return
            print("connected. type an item number or text per line (several separated by ' | '), Ctrl-D to quit",
                  file=sys.stderr, flush=True)
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:
                    break
                for part in filter(None, (x.strip() for x in line.split("|"))):
                    try:
                        await play(f, _resolve(mapping, part))
                    except KeyError:
                        print(f"no such item: {part}", file=sys.stderr, flush=True)
        finally:
            await f.disconnect()
    asyncio.run(go())


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="Custom audio for Furby Connect")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def audio_opts(p):
        p.add_argument("--engine", default=os.environ.get("FLUFFKIT_TTS", "openai"),
                       choices=["openai", "piper", "espeak"])
        p.add_argument("--voice")
        p.add_argument("--instructions")
        p.add_argument("--pitch", type=float, default=float(os.environ.get("FLUFFKIT_PITCH", 0)),
                       help="pitch shift in semitones, tempo unchanged (e.g. 3-4 = more Furby-like)")
        p.add_argument("--gain", type=float, default=0.0, help="extra gain in dB")
        p.add_argument("--music", action="store_true", help="music/sfx: keep dynamics, lighter filtering")

    p = sub.add_parser("tts"); p.add_argument("text"); p.add_argument("-o", "--output", required=True); audio_opts(p)
    p = sub.add_parser("encode"); p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--gp-header", action="store_true", help="add the 48-byte A1800.DLL header"); audio_opts(p)
    p = sub.add_parser("decode"); p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("pack"); p.add_argument("phrases"); p.add_argument("-o", "--output", default="pack.dlc")
    p.add_argument("--base"); p.add_argument("--keep-original-audio", action="store_true"); audio_opts(p)
    p = sub.add_parser("check"); p.add_argument("dlc"); p.add_argument("--export")
    p = sub.add_parser("slots")
    p = sub.add_parser("upload"); p.add_argument("dlc"); p.add_argument("--slot", type=int, default=2)
    p.add_argument("--address"); p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--name", default="TU003410.DLC", help="file name announced to Furby (max 12 chars)")
    p = sub.add_parser("say"); p.add_argument("what", nargs="+", help="item number(s) or text; '-' = keep connection, read stdin")
    p.add_argument("--map", default="pack.json"); p.add_argument("--gap", type=float, default=0.15, help="pause between chained items (s)")
    p.add_argument("--address")
    a = ap.parse_args()

    if a.cmd == "tts":
        tts(a.text, Path(a.output), a.engine, a.voice, a.instructions)
    elif a.cmd == "encode":
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "16k.wav"
            to_pcm16k(Path(a.input), w, a.pitch, a.gain, a.music)
            body = encode_a18_body(w)
        Path(a.output).write_bytes((GP_HEADER if a.gp_header else b"") + body)
        print(f"{a.output}: {(len(body) - 6) / FRAME_BYTES * 0.02:.2f} s, {len(body)} bytes")
    elif a.cmd == "decode":
        decode_body(read_a18_body(Path(a.input)), Path(a.output))
    else:
        {"pack": cmd_pack, "check": cmd_check, "slots": cmd_slots,
         "upload": cmd_upload, "say": cmd_say}[a.cmd](a)


if __name__ == "__main__":
    main()
