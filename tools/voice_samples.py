#!/usr/bin/env python3
"""Turn audio into upload-ready voice samples (e.g. for ElevenLabs Instant Voice Cloning).

Inputs, any mix of files and folders:
  .a18                     A1800 file (with or without the A1800.DLL header)
  .dlc                     Furby Connect DLC: every track of its AMF section
  .amf / AudioMegafiles    firmware audio megafile: every A1800 clip
  .wav .mp3 .m4a .flac …   ordinary audio

Each clip is trimmed of leading/trailing silence, clips shorter than --min-clip are dropped, the
rest is loudness-normalised, and clips are joined (with a short gap) into MP3 files of up to
--chunk seconds until --total seconds are collected. ElevenLabs recommends MP3 at 192 kbps or
more and 1-2 minutes in total for Instant Voice Cloning; more than ~3 minutes does not help.

This only prepares files; it uploads nothing. Only use recordings of a voice you have the right
to clone.

    python3 tools/voice_samples.py my_recordings/ old.a18 -o samples/ --total 120
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fluffkit  # noqa: E402  (A1800 codec + AMF reader)
from dlcpack import DLC  # noqa: E402

AUDIO = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aiff", ".aif", ".caf", ".opus", ".webm"}
SR = 44100


def sh(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-400:])
    return r.stdout


def duration(p: Path) -> float:
    try:
        return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]))
    except (RuntimeError, ValueError):
        return 0.0


def a1800_bodies(path: Path) -> list[bytes]:
    """All A1800 track bodies (u32 len | u16 rate | frames) in an .a18, .dlc or AMF file."""
    data = path.read_bytes()
    if data[:10] == "FURBY".encode("utf-16-le"):
        return DLC(data).tracks
    if path.suffix.lower() == ".a18" or data[:18] == fluffkit.GP_HEADER[:18]:
        return [fluffkit.read_a18_body(path)]
    try:
        return [c for c in fluffkit.amf_clips(data) if c]
    except SystemExit:  # amf_clips() calls die() on anything else
        return []


def collect(inputs: list[Path], work: Path) -> list[Path]:
    """Decode everything to WAV files in work/, in a stable order."""
    files: list[Path] = []
    for p in inputs:
        files += sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
    wavs, n = [], 0
    for f in files:
        ext = f.suffix.lower()
        if ext in AUDIO:
            wavs.append(f)
            continue
        for body in a1800_bodies(f):
            if (len(body) - 6) / 40 * 0.02 < 0.3:     # empty or placeholder track
                continue
            n += 1
            out = work / f"a18_{n:05d}.wav"
            fluffkit.decode_body(body, out)
            wavs.append(out)
    return wavs


def clean(src: Path, dst: Path) -> float:
    """Trim silence at both ends, normalise loudness, 44.1 kHz mono WAV. Returns seconds."""
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
            "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse")
    sh(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", f"{trim},loudnorm=I=-18:TP=-1.5:LRA=11",
        "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return duration(dst)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("voice-samples"))
    ap.add_argument("--total", type=float, default=120, help="seconds of speech to collect (default 120)")
    ap.add_argument("--chunk", type=float, default=30, help="max seconds per output file (default 30)")
    ap.add_argument("--min-clip", type=float, default=0.8, help="drop clips shorter than this after trimming")
    ap.add_argument("--max-clip", type=float, default=20, help="drop clips longer than this (songs, music)")
    ap.add_argument("--gap", type=float, default=0.35, help="silence between joined clips")
    ap.add_argument("--bitrate", default="192k")
    a = ap.parse_args()

    missing = [str(p) for p in a.inputs if not p.exists()]
    if missing:
        sys.exit(f"not found: {', '.join(missing)}  (a path like /Documents/... misses your home folder; use ~/Documents/...)")
    a.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        raw = collect(a.inputs, work)
        print(f"{len(raw)} clips found", file=sys.stderr)
        gap = work / "gap.wav"
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", str(a.gap),
            "-c:a", "pcm_s16le", str(gap)])

        chunks: list[list[Path]] = [[]]
        lens, total, kept = [0.0], 0.0, 0
        for i, src in enumerate(raw):
            if total >= a.total:
                break
            c = work / f"clean_{i:05d}.wav"
            try:
                s = clean(src, c)
            except RuntimeError:
                continue
            if not a.min_clip <= s <= a.max_clip:
                continue
            if lens[-1] + s > a.chunk and chunks[-1]:
                chunks.append([]); lens.append(0.0)
            chunks[-1] += [c, gap]; lens[-1] += s + a.gap; total += s; kept += 1

        for n, parts in enumerate(c for c in chunks if c):
            lst = work / f"list_{n}.txt"
            lst.write_text("".join(f"file '{p}'\n" for p in parts[:-1]))
            out = a.out / f"sample_{n + 1:02d}.mp3"
            sh(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                "-c:a", "libmp3lame", "-b:a", a.bitrate, "-ar", str(SR), "-ac", "1", str(out)])
            print(f"{out}  {duration(out):5.1f} s")
        print(f"{kept} clips, {total:.0f} s of speech in {a.out}/", file=sys.stderr)


if __name__ == "__main__":
    main()
