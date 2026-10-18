"""Switch Furby's persona: build phone/furby-agent/AGENTS.md and the voice, optionally send both to the app.

    python3 tools/persona.py                 # list personas
    python3 tools/persona.py selianne        # build locally (phone/serve.py reads it on the next turn)
    python3 tools/persona.py selianne --push # and PUT both files to the companion app (it reloads at once)

A persona is phone/furby-agent/personas/<name>.md (who it is, how it talks, time of day) plus the shared
rules in common.md (speech, tags, sleep, limits). Its voice and wake words live in furby-config.json
under "personas"; the chosen one is copied into "voice". The app's address comes from FURBY_REMOTE
(default http://192.168.1.156:8770), its token from ~/.config/fluffkit/companion_token.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

PHONE = Path(__file__).resolve().parent.parent / "phone"
AGENT = PHONE / "furby-agent"
CONFIG = PHONE / "furby-config.json"


def put(name: str, body: bytes) -> str:
    base = os.environ.get("FURBY_REMOTE", "http://192.168.1.156:8770")
    token = (Path.home() / ".config" / "fluffkit" / "companion_token").read_text().strip()
    req = urllib.request.Request(f"{base}/file/{name}", data=body, method="PUT",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def main() -> None:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    names = sorted(p.stem for p in (AGENT / "personas").glob("*.md"))
    if len(sys.argv) < 2:
        print("personas:", ", ".join(f"{n}{' *' if n == cfg.get('persona') else ''}" for n in names))
        return
    name = sys.argv[1]
    if name not in names or name not in cfg.get("personas", {}):
        sys.exit(f"unknown persona {name!r}; have: {', '.join(names)}")
    others = [cfg["personas"][n]["name"] for n in names if n != name and n in cfg["personas"]]
    switch = (f"\n## Persoonan vaihto\n\n- `[persoona: nimi]` = vaihdat toiseksi Furbyksi: {', '.join(others)}. "
              "Käytä vain, kun lapsi pyytää vaihtamaan persoonaa tai kutsuu toista nimeltä (\"vaihda Urhoon\", "
              "\"haluan puhua Seliannelle\"). Sano ensin lyhyesti hei hei ja laita merkintä viimeiseksi: "
              "toinen Furby esittäytyy omalla äänellään.\n")
    agents = (AGENT / "personas" / f"{name}.md").read_text(encoding="utf-8").rstrip() + "\n\n" + \
        (AGENT / "common.md").read_text(encoding="utf-8").rstrip() + "\n" + switch
    (AGENT / "AGENTS.md").write_text(agents, encoding="utf-8")
    cfg["persona"] = name
    cfg["voice"] = {**cfg["voice"], **cfg["personas"][name]["voice"]}
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"persona {name}: AGENTS.md built, voice {cfg['voice']['id']}")
    if "--push" in sys.argv:
        for f in [AGENT / "common.md", *sorted((AGENT / "personas").glob("*.md"))]:   # the app builds its own prompt
            print(f.relative_to(AGENT), put(str(f.relative_to(AGENT)), f.read_bytes()))
        print("AGENTS.md:", put("AGENTS.md", agents.encode()))
        print("furby-config.json:", put("furby-config.json", CONFIG.read_bytes()))


if __name__ == "__main__":
    main()
