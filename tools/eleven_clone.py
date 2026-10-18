#!/usr/bin/env python3
"""Create an ElevenLabs voice from your own recordings (Instant Voice Cloning) and print its voice id.

    ELEVENLABS_API_KEY=… python3 tools/eleven_clone.py "Oma ääni" samples/*.mp3 --i-have-the-rights \
        --language fi --test "Hei! Tämä on testi."

Prepare the samples with tools/voice_samples.py (1–2 minutes of clean speech, MP3 192 kbps).
ElevenLabs only allows cloning a voice you own or have explicit permission to use; the
--i-have-the-rights flag is that same declaration, and you are responsible for it.

Use the printed voice id in phone/index.html (const VOICE) or with
`fluffkit.py pack --engine elevenlabs --voice <id>`.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://api.elevenlabs.io/v1"


def multipart(fields: list[tuple[str, str]], files: list[Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
    for f in files:
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{f.name}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + f.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def request(method: str, path: str, key: str, body: bytes | None = None, ctype: str | None = None) -> bytes:
    headers = {"xi-api-key": key}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(API + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs {e.code}: {e.read()[:500].decode('utf-8', 'replace')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="name of the new voice in your ElevenLabs account")
    ap.add_argument("files", nargs="+", type=Path, help="audio samples (MP3 192 kbps recommended, 1–2 min total)")
    ap.add_argument("--i-have-the-rights", action="store_true",
                    help="declare that you own this voice or have permission to clone it (required)")
    ap.add_argument("--description", default="")
    ap.add_argument("--language", help="label, e.g. fi")
    ap.add_argument("--remove-background-noise", action="store_true")
    ap.add_argument("--test", metavar="TEXT", help="after creating, render TEXT with the new voice to voice_test.mp3")
    a = ap.parse_args()

    if not a.i_have_the_rights:
        sys.exit("refusing: pass --i-have-the-rights only for a voice you own or may clone (ElevenLabs terms)")
    key = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("ELEVENLABS_API_KEY is not set")
    missing = [f for f in a.files if not f.is_file()]
    if missing:
        sys.exit(f"not found: {', '.join(map(str, missing))}")

    fields = [("name", a.name), ("description", a.description),
              ("remove_background_noise", "true" if a.remove_background_noise else "false")]
    if a.language:
        fields.append(("labels", json.dumps({"language": a.language})))
    body, ctype = multipart(fields, a.files)
    voice_id = json.loads(request("POST", "/voices/add", key, body, ctype))["voice_id"]
    print(f"voice_id: {voice_id}")

    if a.test:
        tts = {"text": a.test, "model_id": "eleven_flash_v2_5"}
        if a.language:
            tts["language_code"] = a.language
        audio = request("POST", f"/text-to-speech/{voice_id}?output_format=mp3_44100_128", key,
                        json.dumps(tts).encode(), "application/json")
        Path("voice_test.mp3").write_bytes(audio)
        print("test: voice_test.mp3")


if __name__ == "__main__":
    main()
