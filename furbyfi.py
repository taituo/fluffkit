#!/usr/bin/env python3
"""
furby-fi: suomenkielinen ääni Furby Connectiin (2016).

Putki:  teksti -> TTS (OpenAI / Piper / espeak-ng) -> 16 kHz mono WAV
        -> A18 (korjattu avoin A1800-enkooderi) -> DLC (phrase pack)
        -> BLE-lataus PyFluffilla -> laukaisu toiminnolla 75/0/y/z

Komennot:
  tts     "teksti" -o out.wav              tekstistä puheeksi
  encode  in.wav -o out.a18                WAV/MP3/mitä vain -> Furbyn A18
  decode  in.a18 -o out.wav                A18 -> WAV (kuuntelua varten)
  pack    fraasit.txt -o furby_fi.dlc      rakenna fraasipaketti (DLC)
  check   furby_fi.dlc                     tarkista paketti, pura äänet WAViksi
  upload  furby_fi.dlc                     lataa Furbyyn (poista -> lataa -> load -> activate)
  say     3 | "hei"                        soita fraasi numerolla tai tekstillä
  slots                                    näytä vapaat fraasipaikat (75/x/y/z)

Riippuvuudet: python 3.11+, ffmpeg, a1800_codec (Releases tai: cd a1800 && cargo build --release),
upload/say: pip install bleak + PyFluff (git clone https://github.com/martinwoodward/PyFluff).
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

CACHE = Path(os.environ.get("FURBY_FI_CACHE", Path.home() / ".cache" / "furby-fi"))
BASE_DLC_URL = "https://raw.githubusercontent.com/ctxis/Furby/master/dlc/dlc2/tu003410.dlc"
BASE_DLC_SHA256 = "efe11a82a7f837ebd8ab7a76e5873e0be4a0aa23ccedc73cb9c4601139c8e203"

SR = 16000
BITRATE = 16000            # kaikki Furbyn omat raidat ovat 16 kbps
FRAME_SAMPLES = 320        # 20 ms
FRAME_BYTES = BITRATE // 800 * 2   # 40 tavua / kehys
# A1800.DLL:n kirjoittama 48 tavun otsake (kopioitu DLL:n tuottamista tiedostoista)
GP_HEADER = bytes.fromhex(
    "00ff00ff47454e4552414c504c55532053500000fe020e001000803e"
    "0000803e00000000000000000001000000000000")
MINIFIED_TRACK_BYTES = 128  # sama kuin alkuperäisessä Context IS -demossa (toimi oikealla Furbyllä)


def die(msg: str) -> None:
    print(f"virhe: {msg}", file=sys.stderr)
    sys.exit(1)


def codec_bin() -> str:
    for c in (os.environ.get("A1800_CODEC"), HERE / "bin" / "a1800_codec",
              HERE / "a1800" / "target" / "release" / "a1800_codec",
              shutil.which("a1800_codec")):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    die("a1800_codec puuttuu: aja `cargo build --release` kansiossa a1800")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"{cmd[0]} epäonnistui:\n{r.stderr[-2000:]}")


# ---------------------------------------------------------------- TTS

def tts(text: str, out_wav: Path, engine: str, voice: str | None, instructions: str | None) -> None:
    if engine == "openai":
        key = os.environ.get("OPENAI_API_KEY") or die("OPENAI_API_KEY puuttuu")
        body = {
            "model": os.environ.get("FURBY_TTS_MODEL", "gpt-4o-mini-tts"),
            "voice": voice or os.environ.get("FURBY_TTS_VOICE", "coral"),
            "input": text,
            "response_format": "wav",
        }
        ins = instructions or os.environ.get(
            "FURBY_TTS_INSTRUCTIONS",
            "Puhu suomea. Olet pieni, iloinen ja vähän höpsö karvainen otus. "
            "Puhu selkeästi, innokkaasti ja hieman nopeasti.")
        if ins:
            body["instructions"] = ins
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out_wav.write_bytes(r.read())
    elif engine == "piper":
        model = voice or os.environ.get("FURBY_PIPER_MODEL") or die(
            "anna --voice polku/fi_FI-harri-medium.onnx tai FURBY_PIPER_MODEL")
        p = subprocess.run(["piper", "--model", model, "--output_file", str(out_wav)],
                           input=text, text=True, capture_output=True)
        if p.returncode:
            die(p.stderr[-1500:])
    elif engine == "espeak":
        run(["espeak-ng", "-v", voice or "fi", "-s", "150", "-w", str(out_wav), text])
    else:
        die(f"tuntematon TTS: {engine}")


# ---------------------------------------------------------------- A18

def to_pcm16k(src: Path, dst: Path, pitch: float, gain_db: float) -> None:
    """Mikä tahansa ääni -> 16 kHz mono s16. Ylipäästö + normalisointi Furbyn pikkukaiuttimelle."""
    af = ["highpass=f=120", "lowpass=f=7000"]
    if pitch:
        f = 2 ** (pitch / 12)
        af += [f"asetrate={SR}*{f:.5f}", f"aresample={SR}", f"atempo={1 / f:.5f}"]
    af += ["dynaudnorm=f=150:g=15", "loudnorm=I=-14:TP=-1.0:LRA=7"]
    if gain_db:
        af.append(f"volume={gain_db}dB")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", ",".join(af),
         "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])


def encode_a18_body(wav16: Path) -> bytes:
    """Palauttaa raidan Furbyn/DLL:n muodossa: u32 (kehystavut+2) | u16 16000 | kehykset."""
    raw = wav16.read_bytes()
    # etsi data-chunk
    i = 12
    while i < len(raw) - 8:
        cid, sz = raw[i:i + 4], struct.unpack("<I", raw[i + 4:i + 8])[0]
        if cid == b"data":
            pcm = raw[i + 8:i + 8 + sz]
            break
        i += 8 + sz + (sz & 1)
    else:
        die("WAV ilman data-chunkia")
    n = len(pcm) // 2
    # +1 kehys hiljaisuutta loppuun: avoin enkooderi on kehyksen jäljessä DLL:ään nähden,
    # ensimmäinen kehys pudotetaan alla -> ajoitus täsmää DLL:n kanssa.
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
    frames = frames[FRAME_BYTES:]  # pudota ensimmäinen kehys (ks. yllä)
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
    # avoin dekooderi odottaa pelkkää kehystavumäärää
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
        print(f"ladataan pohja-DLC {BASE_DLC_URL}")
        with urllib.request.urlopen(BASE_DLC_URL, timeout=60) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != BASE_DLC_SHA256:
            die("pohja-DLC:n tarkiste ei täsmää")
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
    """Rivi on joko polku (.wav/.mp3/.a18) tai teksti TTS:lle. Välimuisti hashin mukaan."""
    p = Path(item)
    if p.suffix.lower() == ".a18" and p.exists():
        return read_a18_body(p), p.name
    key = hashlib.sha256(json.dumps([item, args.engine, args.voice, args.instructions,
                                     args.pitch, args.gain]).encode()).hexdigest()[:16]
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
        to_pcm16k(src, w16, args.pitch, args.gain)
        body = encode_a18_body(w16)
    cached.write_bytes(body)
    return body, item


def cmd_pack(args) -> None:
    phrases = read_phrases(Path(args.phrases))
    if len(phrases) > len(SLOTS):
        die(f"liikaa fraaseja ({len(phrases)}), paikkoja on {len(SLOTS)}")
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
    print(f"\n{out}  {kb:.0f} kB  (BLE ~4 kB/s -> noin {kb / 4 / 60:.1f} min lataus)\nkartta: {map_path}")
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
            print(f"  VIRHE fraasi {k}: {tr} {ln} {br}")
    print(f"tarkistus: {ok}/{len(mapping)} fraasia osoittaa oikeaan raitaan, DLC jäsentyy ({len(D.tracks)} raitaa)")


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
        die("PyFluff puuttuu: git clone https://github.com/martinwoodward/PyFluff && pip install -e PyFluff "
            "(tai PYFLUFF_PATH=/polku/PyFluff)")
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
            print(f"poistetaan slot {args.slot}")
            await m.delete_dlc(args.slot)
            await asyncio.sleep(2)
            print("ladataan... (seuraa Furbyn debug-näyttöä: 1 = latautuu, 2 = valmis)")
            await m.upload_dlc(Path(args.dlc), slot=args.slot, timeout=args.timeout)
            await m.load_dlc(args.slot)
            await asyncio.sleep(1)
            await m.activate_dlc()
            await f.set_antenna_color(0, 255, 0)
            print("valmis. Jos fraasit eivät soi: käynnistä Furby uudelleen ja aja `say 1`.")
        finally:
            await f.disconnect()
    asyncio.run(go())


def cmd_say(args) -> None:
    import asyncio
    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
    key = args.what
    if key not in mapping:
        hits = [k for k, m in mapping.items() if key.lower() in m["text"].lower()]
        if not hits:
            die(f"ei fraasia: {key}")
        key = hits[0]
    c = mapping[key]["action"]

    async def go():
        f = await _connected(args.address)
        try:
            await f.trigger_action(*c)
            await asyncio.sleep(mapping[key]["seconds"] + 0.5)
        finally:
            await f.disconnect()
    print(f"{key}: {'/'.join(map(str, c))}  {mapping[key]['text']}")
    asyncio.run(go())


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="Suomenkielinen ääni Furby Connectiin")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def audio_opts(p):
        p.add_argument("--engine", default=os.environ.get("FURBY_TTS", "openai"),
                       choices=["openai", "piper", "espeak"])
        p.add_argument("--voice")
        p.add_argument("--instructions")
        p.add_argument("--pitch", type=float, default=float(os.environ.get("FURBY_PITCH", 0)),
                       help="sävelkorkeus puolisävelinä, esim. 4 = Furbymaisempi")
        p.add_argument("--gain", type=float, default=0.0, help="lisävahvistus dB")

    p = sub.add_parser("tts"); p.add_argument("text"); p.add_argument("-o", "--output", required=True); audio_opts(p)
    p = sub.add_parser("encode"); p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--gp-header", action="store_true", help="lisää A1800.DLL:n 48 tavun otsake"); audio_opts(p)
    p = sub.add_parser("decode"); p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("pack"); p.add_argument("phrases"); p.add_argument("-o", "--output", default="furby_fi.dlc")
    p.add_argument("--base"); p.add_argument("--keep-original-audio", action="store_true"); audio_opts(p)
    p = sub.add_parser("check"); p.add_argument("dlc"); p.add_argument("--export")
    p = sub.add_parser("slots")
    p = sub.add_parser("upload"); p.add_argument("dlc"); p.add_argument("--slot", type=int, default=2)
    p.add_argument("--address"); p.add_argument("--timeout", type=float, default=900)
    p = sub.add_parser("say"); p.add_argument("what"); p.add_argument("--map", default="furby_fi.json")
    p.add_argument("--address")
    a = ap.parse_args()

    if a.cmd == "tts":
        tts(a.text, Path(a.output), a.engine, a.voice, a.instructions)
    elif a.cmd == "encode":
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "16k.wav"
            to_pcm16k(Path(a.input), w, a.pitch, a.gain)
            body = encode_a18_body(w)
        Path(a.output).write_bytes((GP_HEADER if a.gp_header else b"") + body)
        print(f"{a.output}: {(len(body) - 6) / FRAME_BYTES * 0.02:.2f} s, {len(body)} tavua")
    elif a.cmd == "decode":
        decode_body(read_a18_body(Path(a.input)), Path(a.output))
    else:
        {"pack": cmd_pack, "check": cmd_check, "slots": cmd_slots,
         "upload": cmd_upload, "say": cmd_say}[a.cmd](a)


if __name__ == "__main__":
    main()
