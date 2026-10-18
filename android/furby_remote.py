#!/usr/bin/env python3
"""Remote control for the Furby companion app (android/), so nobody has to touch the phone.

    python3 android/furby_remote.py setup --eleven-key-file ~/11labs.md     # once, phone on adb
    python3 android/furby_remote.py push                                   # phone/ config + persona + packs
    python3 android/furby_remote.py say "Hei, minä olen Urho!"
    python3 android/furby_remote.py chat "Kerro tarina dinosauruksesta"
    python3 android/furby_remote.py sleep | wake | tag tanssi | listen off | persona selianne | state | log

`setup` pushes the keys as secrets.json over adb (the app imports them into EncryptedSharedPreferences and
deletes the file), with a remote token kept in ~/.config/fluffkit/companion_token, and forwards port 8770.
Without --host the commands go through that adb forward; --host 192.168.1.156 (or a Tailscale name) goes direct.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHONE = HERE.parent / "phone"
CONF = Path.home() / ".config" / "fluffkit"
TOKEN_FILE = CONF / "companion_token"
PKG = "fluffkit.companion"
FILES_DIR = f"/sdcard/Android/data/{PKG}/files"
PORT = 8770


def token() -> str:
    if not TOKEN_FILE.exists():
        CONF.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(secrets.token_urlsafe(24))
        TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text().strip()


def adb(*args: str) -> str:
    return subprocess.run(["adb", *args], check=True, capture_output=True, text=True).stdout


def first_line(path: str) -> str:
    for line in Path(path).expanduser().read_text().splitlines():
        if line.strip():
            return line.strip()
    raise SystemExit(f"{path} is empty")


def setup(a) -> None:
    s = {"remote_token": token()}
    if a.eleven_key_file:
        s["elevenlabs_key"] = first_line(a.eleven_key_file)
    bearer = Path(a.bearer_file).expanduser()
    if bearer.exists():
        s["llm_bearer"] = bearer.read_text().strip()
    if a.llm_url:
        s["llm_url"] = a.llm_url
    if a.model:
        s["llm_model"] = a.model
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(s, f)
    try:
        os.chmod(f.name, 0o600)
        adb("shell", "mkdir", "-p", FILES_DIR)
        adb("push", f.name, f"{FILES_DIR}/secrets.json")
    finally:
        os.unlink(f.name)
    adb("shell", "am", "broadcast", "-a", f"{PKG}.DEBUG", "--es", "cmd", "reload")   # imports secrets.json
    adb("forward", f"tcp:{PORT}", f"tcp:{PORT}")
    if a.reverse_gateway:
        adb("reverse", "tcp:8788", "tcp:8788")   # the default brain URL is the Mac's gateway on 127.0.0.1:8788
    print("pushed:", ", ".join(k for k in s if k != "remote_token"), "+ remote token; forwarded", PORT)


def call(a, method: str, path: str, body: bytes | None = None) -> str:
    base = f"http://{a.host}:{PORT}" if a.host else f"http://127.0.0.1:{PORT}"
    req = urllib.request.Request(base + path, data=body, method=method,
                                 headers={"Authorization": f"Bearer {token()}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{e.code}: {e.read().decode()}")


def cmd(a, name: str, text: str = "") -> None:
    print(call(a, "POST", "/cmd", json.dumps({"cmd": name, "text": text}).encode()))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", help="phone address (default: adb forward on 127.0.0.1)")
    sub = p.add_subparsers(dest="what", required=True)
    s = sub.add_parser("setup", help="push keys + remote token over adb")
    s.add_argument("--eleven-key-file", help="file whose first line is the ElevenLabs API key")
    s.add_argument("--bearer-file", default=str(CONF / "gateway_bearer"))
    s.add_argument("--llm-url", help="brain URL, e.g. http://192.168.1.10:8788/v1")
    s.add_argument("--model")
    s.add_argument("--no-reverse", dest="reverse_gateway", action="store_false")
    sub.add_parser("push", help="upload phone/furby-config.json, AGENTS.md and packs.json")
    sub.add_parser("state"); sub.add_parser("log")
    for name in ("say", "chat", "tag", "act", "antenna", "listen", "threshold", "hear", "persona"):
        sub.add_parser(name).add_argument("text", nargs="+")
    for name in ("sleep", "wake", "reload", "forget", "rescan"):
        sub.add_parser(name)
    a = p.parse_args()

    if a.what == "setup":
        setup(a)
    elif a.what == "push":
        agent = PHONE / "furby-agent"
        files = [(PHONE / "furby-config.json", "furby-config.json"), (agent / "AGENTS.md", "AGENTS.md"),
                 (PHONE / "packs.json", "packs.json"), (agent / "common.md", "common.md")]
        files += [(f, f"personas/{f.name}") for f in sorted((agent / "personas").glob("*.md"))]
        for local, name in files:
            if local.exists():
                print(call(a, "PUT", f"/file/{name}", local.read_bytes()))
    elif a.what == "state":
        print(json.dumps(json.loads(call(a, "GET", "/state")), ensure_ascii=False, indent=1))
    elif a.what == "log":
        print(call(a, "GET", "/log"))
    else:
        cmd(a, a.what, " ".join(getattr(a, "text", [])))


if __name__ == "__main__":
    sys.exit(main())
